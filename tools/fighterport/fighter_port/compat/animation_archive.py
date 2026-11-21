"""Lossless FigaTree stream compaction and public-symbol alias packing.

The engine resolves action symbols inside each loaded archive. Equal animations
can share a span only if that archive retains every action's public symbol.
"""
import struct
from vault.echo.datroot import parse,build

def tracks(blob):
    data,rel,roots,xrefs=parse(blob)
    if not roots or xrefs or len({r for r,_ in roots})!=1:raise ValueError('One FigaTree root domain required')
    r=roots[0][0];cp,tp=struct.unpack_from('>II',data,r+12)
    stop=data.index(255,cp);counts=data[cp:stop]
    if not 1<=len(counts)<=140 or any(c>127 for c in counts):raise ValueError('Invalid signed FigaTree node counts')
    rows=[]
    for i in range(sum(counts)):
        at=tp+12*i;length=struct.unpack_from('>H',data,at)[0];ptr=struct.unpack_from('>I',data,at+8)[0]
        if ptr+length>len(data):raise ValueError('Truncated FOBJ stream')
        rows.append((data[at:at+8],data[ptr:ptr+length]))
    if set(rel)!={r+12,r+16}|{tp+12*i+8 for i in range(len(rows))}:raise ValueError('Unexpected FigaTree relocations')
    return data[r:r+12],counts,tuple(rows),tuple(n for _,n in roots)

def compact(blob,*,symbols=None):
    head,counts,rows,names=tracks(blob)
    names=tuple(symbols) if symbols is not None else names
    if not names or len(set(names))!=len(names):raise ValueError('Unique public symbols required')
    counts+=b'\xff';counts+=bytes(-len(counts)%4)
    cp=20;tp=cp+len(counts)
    data=bytearray(head+struct.pack('>II',cp,tp)+counts+bytes(12*len(rows)))
    rel=[12,16];buffers={}
    for i,(desc,buf) in enumerate(rows):
        if buf not in buffers:
            data+=bytes(-len(data)%4);buffers[buf]=len(data);data+=buf
        data[tp+12*i:tp+12*i+12]=desc+struct.pack('>I',buffers[buf]);rel.append(tp+12*i+8)
    data+=bytes(-len(data)%4)
    result=build(bytes(data),rel,[(0,n) for n in names],[])
    if tracks(result)[:3]!=tracks(blob)[:3]:raise ValueError('Compaction changed FOBJ content')
    return result

def track_fingerprint(blob):
    """Hash the same lossless animation identity used for alias grouping.

    Public symbol strings and container offsets may change during assembly;
    clock header, node counts, channel descriptors and streams may not.
    """
    import hashlib
    head,counts,rows,_=tracks(blob)
    digest=hashlib.sha256()
    for part in (head,counts,*(p for descriptor,stream in rows for p in (descriptor,stream))):
        digest.update(struct.pack('>Q',len(part)));digest.update(part)
    return digest.hexdigest()


def pack(entries, *, rig_sha256=None, clip_receipts=None):
    """Entries are (public symbol, archive bytes); return bank, spans, receipt."""
    import hashlib
    entries=list(entries)
    if (rig_sha256 is None)!=(clip_receipts is None):raise ValueError('Rig identity and all clip receipts must be supplied together')
    if rig_sha256 is not None:
        if not isinstance(rig_sha256,str) or len(rig_sha256)!=64 or set(clip_receipts)!={symbol for symbol,_ in entries}:
            raise ValueError('Exact clip receipt coverage and rig fingerprint required')
        from shared.ingame.rig_preflight import figatree_nodes
        for symbol,blob in entries:
            row=clip_receipts[symbol]
            if row.get('rig_sha256')!=rig_sha256 or row.get('nodes')!=figatree_nodes(blob):
                raise ValueError('Clip receipt belongs to a different or unbound frozen rig')
            pinned=row.get('blob',row.get('inputs',{}).get('packed',{}))
            identity=row.get('track_sha256')
            if identity is not None:
                if identity!=track_fingerprint(blob):raise ValueError('Clip receipt does not bind the actual animation streams')
            elif pinned.get('sha256')!=hashlib.sha256(blob).hexdigest():
                raise ValueError('Clip receipt does not bind the actual archive bytes')
    groups={};seen=set();input_bytes=0
    for symbol,blob in entries:
        if symbol in seen:raise ValueError('Duplicate action symbol')
        seen.add(symbol);view=tracks(blob)
        if symbol not in view[3]:raise ValueError('Requested public symbol is absent')
        key=view[:3]
        if key not in groups:groups[key]=[blob,[]]
        groups[key][1].append(symbol);input_bytes+=(len(blob)+31)&~31
    bank=bytearray();spans={};aliases=[]
    for blob,names in groups.values():
        packed=compact(blob,symbols=names);at=len(bank)
        for name in names:spans[name]=(at,len(packed))
        bank+=packed;bank+=bytes(-len(bank)%32)
        if len(names)>1:aliases.append(names)
    receipt=dict(input_bytes=input_bytes,bytes=len(bank),symbols=len(seen),unique_archives=len(groups),aliases=aliases)
    if rig_sha256 is not None:receipt.update(rig_sha256=rig_sha256,clip_rig_binding='ALL_INPUT_CLIPS_BOUND',source_acceptance='NOT_INFERRED_FROM_CODEC_RECEIPTS')
    return bytes(bank),spans,receipt


def restore_joint_streams(candidate, reference, joints):
    """Restore explicit joint channels from a clock/domain-matched archive.

    The caller owns source provenance and skeleton identity. No retiming,
    remapping or curve fitting is inferred. Every other channel stays exact.
    """
    head,counts,rows,names=tracks(candidate);rh,rc,rr,_=tracks(reference)
    if head!=rh or len(counts)!=len(rc):raise ValueError('Source joint restoration needs the same clock and node domain')
    selected=set(joints)
    if not selected or any(type(i) is not int or not 0<=i<len(counts) for i in selected):raise ValueError('Explicit valid source joint indices required')
    merged=[];nc=[];a=b=0
    for j,(count,refcount) in enumerate(zip(counts,rc)):
        chosen=rr[b:b+refcount] if j in selected else rows[a:a+count]
        merged.extend(chosen);nc.append(len(chosen));a+=count;b+=refcount
    result=_build_tracks(head,nc,merged,names)
    if tracks(result)[:3]!=(head,bytes(nc),tuple(merged)):raise ValueError('Restored joint stream readback differs')
    return result


def _build_tracks(head,counts,rows,names):
    """Rebuild an already-decoded FigaTree without interpreting stream bytes."""
    counts=bytes(counts);cb=counts+b'\xff';cb+=bytes(-len(cb)%4);tp=20+len(cb)
    data=bytearray(head+struct.pack('>II',20,tp)+cb+bytes(12*len(rows)));rel=[12,16];buffers={}
    for i,(desc,stream) in enumerate(rows):
        if len(desc)!=8:raise ValueError('Invalid FOBJ descriptor')
        if stream not in buffers:
            data+=bytes(-len(data)%4);buffers[stream]=len(data);data+=stream
        data[tp+12*i:tp+12*i+12]=desc+struct.pack('>I',buffers[stream]);rel.append(tp+12*i+8)
    return build(bytes(data),rel,[(0,n) for n in names],[])


def copy_joint_channels(candidate,reference,identities):
    """Copy explicit numeric ``(node, type)`` FOBJ rows from a peer clip.

    Both clips must have the same clock/header and node domain. Requested rows
    may replace an existing identity or append a missing identity to that node;
    every unrequested descriptor and stream is carried through verbatim. This
    is a byte-level splice, not decoded curve authoring or skeleton inference.
    """
    head,counts,rows,names=tracks(candidate);rh,rc,rr,_=tracks(reference)
    if head!=rh or len(counts)!=len(rc):raise ValueError('Channel copy needs the same clock/header and node domain')
    requested=list(identities)
    if not requested or len(set(requested))!=len(requested):raise ValueError('Unique nonempty channel identities required')
    allowed={1,2,3,5,6,7,8,9,10}
    if any(not isinstance(x,tuple) or len(x)!=2 or type(x[0]) is not int or type(x[1]) is not int or
           not 0<=x[0]<len(counts) or x[1] not in allowed for x in requested):
        raise ValueError('Invalid channel identity')
    def indexed(node_counts,node_rows):
        result={};by_node=[];at=0
        for node,count in enumerate(node_counts):
            current=[]
            for _ in range(count):
                row=node_rows[at];identity=(node,row[0][4]);at+=1
                if identity in result:raise ValueError('Duplicate channel identity in archive')
                result[identity]=row;current.append((identity,row))
            by_node.append(current)
        if at!=len(node_rows):raise ValueError('Channel counts differ from rows')
        return result,by_node
    source,_=indexed(rc,rr);_,target=indexed(counts,rows)
    if any(identity not in source for identity in requested):raise ValueError('Requested channel identity missing from reference')
    selected=set(requested);merged=[];new_counts=[]
    for node,current in enumerate(target):
        present={identity for identity,_ in current}
        for identity,row in current:merged.append(source[identity] if identity in selected else row)
        for identity in sorted(selected):
            if identity[0]==node and identity not in present:merged.append(source[identity])
        new_counts.append(len(merged)-sum(new_counts))
    result=_build_tracks(head,new_counts,merged,names)
    actual=tracks(result)
    if actual[:3]!=(head,bytes(new_counts),tuple(merged)):raise ValueError('Copied channel stream readback differs')
    return result
