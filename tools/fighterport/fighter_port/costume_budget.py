"""Actual serialized costume budget; choose texture work from measured bytes."""
import struct
from .compat.rig_inventory import Archive, costume_inventory
from .mesh_bindings import inventory
from shared.rendering.datprobe import gx_image_size


def measure(payload, root_name=None):
    dat = Archive(payload)
    topology = costume_inventory(payload, root_name)
    bindings = inventory(payload, root_name=topology['root'])
    images = {}
    for joint in topology['joints']:
        for dobj in joint['dobj_offsets']:
            material = dat.ptr(dobj+8)
            texture = dat.ptr(material+8) if material is not None else None
            seen = set()
            while texture is not None:
                if texture in seen:
                    raise ValueError('Cyclic texture chain')
                seen.add(texture)
                dat.require(texture, 0x54)
                desc = dat.ptr(texture+0x4c)
                if desc is not None:
                    dat.require(desc, 0x18)
                    width, height = struct.unpack_from('>HH', payload, 32+desc+4)
                    fmt, mipmaps = dat.u32(desc+8), dat.u32(desc+12)
                    if not width or not height or mipmaps:
                        raise ValueError('Budget requires nonempty non-mipmapped images; mip chain needs explicit inventory')
                    size = gx_image_size(fmt, width, height)
                    offset = dat.ptr(desc)
                    dat.require(offset, size)
                    row = dict(offset=offset+32, bytes=size, width=width, height=height, format=fmt)
                    if offset in images and images[offset] != row:
                        raise ValueError('Shared texture has incompatible descriptors')
                    images[offset] = row
                texture = dat.ptr(texture)
    spans = sorted((offset, offset+row['bytes']) for offset,row in images.items())
    if any(b > c for (_,b),(c,_) in zip(spans,spans[1:])):
        raise ValueError('Overlapping texture payloads')
    texture_bytes = sum(r['bytes'] for r in images.values())
    display_bytes = sum(r['display_bytes'] for r in bindings['pobjs'])
    remaining = len(payload)-texture_bytes-display_bytes
    if remaining < 0:
        raise ValueError('Partition exceeds archive')
    return dict(schema='costume-budget-v1', status='SERIALIZED_COSTUME_MEASURED', sha256=topology['sha256'],
                costume_dat_bytes=len(payload), joint_count=topology['joint_count'], dobj_count=topology['dobj_descriptor_count'],
                embedded_texture_image_payload_bytes=texture_bytes, geometry_display_list_bytes=display_bytes,
                unpartitioned_dat_bytes=remaining, texture_images=list(images.values()),
                texture_fraction=texture_bytes/len(payload),
                next_step='REDUCE_TEXTURE_DIMENSIONS_FIRST' if texture_bytes > len(payload)/2 else 'INSPECT_GEOMETRY_AND_OTHER_STRUCTURES',
                scope='Unique tiled image payloads and display lists; other includes palettes, vertex data, descriptors, binds and padding. Not live memory admission.',
                native_accepted=False)


def resize_texture(image, max_dimension, *, preserve=False):
    """Apply an explicit dimension policy before encoding, preserving RGBA."""
    from PIL import Image
    if type(max_dimension) is not int or max_dimension <= 0 or type(preserve) is not bool:
        raise ValueError('Positive integer texture dimension and boolean preservation required')
    before = list(image.size)
    result = image.convert('RGBA')
    if not preserve and max(before) > max_dimension:
        ratio = max_dimension/max(before)
        result = result.resize(tuple(max(1,round(x*ratio)) for x in before), Image.Resampling.LANCZOS)
    return result, dict(before=before, after=list(result.size), preserved=preserve,
                        method='UNCHANGED' if list(result.size)==before else 'LANCZOS_RGBA',
                        scope='Decoded pixels only; remeasure encoded DAT and review alpha/face before acceptance.')
