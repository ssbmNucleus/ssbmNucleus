"""costume_assets.py -- the ONE canonical way to build a costume's portrait
assets (CSP + stock icon) from its DAT.

Every producer of a vault costume -- the unified import, skin-lab saves, the
modpack-duel generator, the "regenerate CSP" actions -- should call
`build_csp_and_stock` instead of re-implementing the render/recolor glue. The
real work still lives in `generate_csp` (HSDRawViewer headless render with the
character's proper anim + camera assets) and `shared.rendering.stock_gen.generate_stock`
(deterministic recolor / head-shot crop); this module just wires them together
with the agreed fallbacks so the result is identical no matter who asks.

The character and costume color are auto-detected from the DAT content by
`generate_csp` (DATParser.detect_character), so the temp filename does not
matter -- but we name it after the costume code anyway for readable logs.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile

from core.config import VANILLA_ASSETS_DIR
from generate_csp import generate_csp, generate_head_shot
from shared.rendering.stock_gen import (STYLE_RENDER, generate_stock, recolor_gw_stock,
                              recolor_gw_stock_rgb)

# Characters whose stock icon is DERIVED (recolored) from the vanilla one rather
# than rendered/texture-diffed: Mr. Game & Watch carries no color in his model
# (the game recolors him from GAMEWATCH_COLOR by slot), so he's always a solid
# color -- recoloring the vanilla icon is exact and can't fail to a white render.
_GW_NAMES = ("Mr. Game & Watch", "G&W")

# A portrait has to SHOW the costume, and a fighter's curated CSP scene frames
# the fighter. The two are the same thing for a recolour and for most imports,
# but a fitted model can be a different shape and size from the body it was
# fitted to, and then the curated camera sits inside it: the render comes back
# as a slab of surface with no outline at all, which in the CSS reads as a blank
# rectangle. The symptom is unmistakable in the pixels -- the costume runs off
# all four sides of the frame, so no edge of it can be seen. Measured over
# Melee's own 120 portraits the least-covered edge is never above 0.103, and
# over 36 fitted costumes never above 0.338; the one portrait a verifier called
# blank sat at 0.856. The bar is in the empty band between.
FRAME_ESCAPES = 0.50

logger = logging.getLogger(__name__)


def _edge_cover(png: bytes) -> float | None:
    """Least-covered edge of a portrait, as a share of that edge. None if unreadable."""
    import io

    try:
        import numpy as np
        from PIL import Image
        opaque = np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))[:, :, 3] > 8
    except Exception:                        # a framing check may never break a render
        return None
    if opaque.size == 0:
        return None
    return float(min(opaque[0].mean(), opaque[-1].mean(),
                     opaque[:, 0].mean(), opaque[:, -1].mean()))


def _shows_the_costume(png: bytes | None, log: logging.Logger) -> bool:
    """Is any outline of the costume inside the frame at all?"""
    if not png:
        return True                          # nothing rendered: not this check's business
    cover = _edge_cover(png)
    if cover is None or cover < FRAME_ESCAPES:
        return True
    log.info(f"portrait: the costume covers {cover:.0%} of every edge of the frame -- "
             "the fighter's own camera is inside it")
    return False


def _fitted_portrait(dat_path: str, size, log: logging.Logger) -> bytes | None:
    """The auto-framed bind-pose render, sized like a portrait. -> png|None.

    The same render the stock icon already asks for, which frames the geometry
    it is given instead of the body the scene was authored around, so a costume
    of any proportions is inside it. It is NOT the vanilla pose, so the caller
    must not let it feed anything that assumes a pixel-aligned render.
    """
    from generate_csp import generate_head_shot
    try:
        rendered, _ = generate_head_shot(dat_path)
    except Exception as exc:
        log.warning(f"portrait: the geometry-framed fallback failed: {exc}")
        return None
    if not rendered or not os.path.exists(rendered):
        return None
    try:
        from PIL import Image
        shot = Image.open(rendered).convert("RGBA")
        if size and shot.size != size:
            shot = shot.resize(size, Image.LANCZOS)
        framed = _png(shot)
    except Exception as exc:
        log.warning(f"portrait: the geometry-framed fallback could not be read: {exc}")
        return None
    finally:
        _drop(rendered)
        _drop(rendered + ".head.json")
    # Only if it actually solved the problem: a costume that overflows every
    # camera is a fit nobody can photograph, and swapping one unusable portrait
    # for another gains nothing while losing the vanilla pose.
    if not _shows_the_costume(framed, log):
        log.warning("portrait: the geometry-framed fallback is no better framed; keeping the fighter's own scene")
        return None
    return framed


def _png(image) -> bytes:
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _vanilla_stock(character: str, costume_code: str) -> tuple[bytes | None, str]:
    """Vanilla stock for this costume code, else the character's default (Nr)."""
    direct = VANILLA_ASSETS_DIR / character / costume_code / "stock.png"
    if direct.exists():
        return direct.read_bytes(), "vanilla"
    if len(costume_code) >= 4:
        default_code = costume_code[:4] + "Nr"
        default = VANILLA_ASSETS_DIR / character / default_code / "stock.png"
        if default.exists():
            return default.read_bytes(), "vanilla_default"
    return None, "missing"


def build_stock(
    character: str,
    costume_code: str,
    dat_data: bytes,
    *,
    dat_path: str | None = None,
    aligned_csp: bytes | None = None,
    is_nana: bool = False,
    popo_stock: bytes | None = None,
    vanilla_fallback: bool = True,
    color_index: int | None = None,
    gw_colors: dict | None = None,
    style: str | None = None,
    log: logging.Logger | None = None,
) -> tuple[bytes | None, str, str | None]:
    """Derive ONE costume's stock icon. Returns (png_bytes|None, source, method).

    source: 'generated' | 'copied_from_popo' | 'vanilla' | 'vanilla_default' |
            'missing'.  method: the generate_stock method when generated (e.g.
            'texture-diff' / 'csp-diff' / 'head-shot'), else mirrors source.

    `aligned_csp` (our OWN render, vanilla pose => pixel-aligned) may feed the
    csp-diff path; community/custom CSPs must not. `vanilla_fallback=False` makes
    a failed generation return (None,'missing',None) instead of a vanilla icon --
    used by the "preview a generated stock" UI which wants generated-only.
    `color_index` is the CSS slot for characters recolored from the vanilla icon
    (Mr. Game & Watch: 0=black default, 1=red, 2=blue, 3=green). `gw_colors`
    ({'fill': (r,g,b), 'outline': (r,g,b,a)}, from a G&W color mod) overrides
    color_index with an arbitrary fill.
    `style` forces one of the two icon looks (STYLE_RECOLOR / STYLE_RENDER)
    instead of letting generate_stock pick; see the vault's two style buttons.
    """
    log = log or logger
    if is_nana:
        if popo_stock:
            return popo_stock, "copied_from_popo", "copied_from_popo"
        return None, "missing", None

    # Mr. Game & Watch: recolor the vanilla icon by slot, never render him (his
    # model has no color, so the render/texture-diff path can only make black or a
    # white head-shot). color_index 0 (default) leaves the vanilla black icon as-is.
    # A model imported onto him draws its own textures: its icon is made like any
    # import's, below, or it would be G&W's silhouette in the slot's fill.
    if character in _GW_NAMES and not _draws_own_textures(dat_data, dat_path):
        # He carries no color of his own (the game tints him by slot), so a
        # render can only produce a white head -- a forced render has no answer.
        if style == STYLE_RENDER:
            return None, "missing", None
        data, source = _vanilla_stock(character, costume_code)
        if data is not None:
            if gw_colors and gw_colors.get('fill') is not None:
                return recolor_gw_stock_rgb(data, gw_colors['fill']), source, "gw_recolor"
            return recolor_gw_stock(data, color_index), source, "gw_recolor"
        return (None, "missing", None) if not vanilla_fallback else (None, source, source)

    own_tmp = None
    if dat_path is None:
        own_tmp = tempfile.mkdtemp(prefix="stock_")
        dat_path = os.path.join(own_tmp, f"{costume_code or 'costume'}.dat")
        with open(dat_path, "wb") as f:
            f.write(dat_data)
    try:
        try:
            generated = generate_stock(
                VANILLA_ASSETS_DIR, character, costume_code or "",
                modded_dat_path=dat_path,
                modded_csp=aligned_csp,
                head_shot_provider=lambda: generate_head_shot(dat_path),
                style=style)
            if generated:
                stock_bytes, method = generated
                log.info(f"Generated stock for {costume_code} via {method}")
                return stock_bytes, "generated", method
        except Exception as e:
            log.warning(f"Stock generation failed for {costume_code}: {e}")
        if vanilla_fallback:
            data, source = _vanilla_stock(character, costume_code)
            return data, source, source
        return None, "missing", None
    finally:
        if own_tmp:
            shutil.rmtree(own_tmp, ignore_errors=True)


def build_csp_and_stock(
    character: str,
    costume_code: str,
    dat_data: bytes,
    *,
    existing_csp: bytes | None = None,
    existing_stock: bytes | None = None,
    paired_dat_data: bytes | None = None,
    is_nana: bool = False,
    popo_csp: bytes | None = None,
    popo_stock: bytes | None = None,
    allow_stock_gen: bool = True,
    color_index: int | None = None,
    gw_colors: dict | None = None,
    log: logging.Logger | None = None,
) -> dict:
    """Return {csp, csp_source, stock, stock_source} for one costume.

    `color_index` / `gw_colors` color Mr. Game & Watch (his color is engine-side,
    not in the DAT): color_index picks a vanilla slot (0=black..3=green) for both
    the CSP render and the stock recolor; gw_colors ({'fill': (r,g,b),
    'outline': (r,g,b,a)}, from a G&W color mod) overrides with arbitrary colors.

    csp/stock are PNG bytes (or None if unavailable). *_source is provenance:
    'imported' (came in with the costume), 'generated', 'copied_from_popo',
    'vanilla', 'vanilla_default', or 'missing'.

    Rules (identical to the unified import flow):
      CSP    -- existing wins; else Ice Climbers Popo composites with its Nana
                (paired_dat_data); else Nana copies Popo (popo_csp); else render
                via generate_csp (proper anim + camera).
      stock  -- existing wins; else Nana copies Popo (popo_stock); else recolor
                the vanilla icon via generate_stock (aligned to our own render
                when we just generated the CSP); else vanilla / default fallback.

    `allow_stock_gen=False` skips the recolor step: a missing stock falls
    straight back to the vanilla icon (Nana still copies Popo). The ISO-scan
    bulk import uses this -- generate_stock is the slow part of a 90-skin batch
    and its result is approximate anyway.
    """
    log = log or logger
    tmp_dir = tempfile.mkdtemp(prefix="csp_assets_")
    dat_path = os.path.join(tmp_dir, f"{costume_code or 'costume'}.dat")
    with open(dat_path, "wb") as f:
        f.write(dat_data)

    csp_data = existing_csp
    csp_source = "imported" if existing_csp else None
    stock_data = existing_stock
    stock_source = "imported" if existing_stock else None
    # Our own render is pixel-aligned with the vanilla one only while it uses
    # the fighter's own scene; the geometry-framed fallback below is a different
    # camera and pose, so it must not be offered to the csp-diff stock path.
    csp_aligned = False

    try:
        # ---- CSP -------------------------------------------------------------
        if csp_data is None:
            if paired_dat_data is not None:
                nana_path = os.path.join(tmp_dir, "PlNnPair.dat")
                with open(nana_path, "wb") as f:
                    f.write(paired_dat_data)
                try:
                    out = generate_csp(dat_path, paired_dat_filepath=nana_path)
                    if out and os.path.exists(out):
                        with open(out, "rb") as f:
                            csp_data = f.read()
                        csp_source, csp_aligned = "generated", True
                        _drop(out)
                    else:
                        log.warning(f"composite CSP generation failed for {costume_code}")
                except Exception as e:
                    log.warning(f"composite CSP generation error for {costume_code}: {e}")
            elif is_nana:
                if popo_csp:
                    csp_data, csp_source = popo_csp, "copied_from_popo"
            else:
                try:
                    out = generate_csp(dat_path, color_index=color_index,
                                       gw_colors=gw_colors)
                    if out and os.path.exists(out):
                        with open(out, "rb") as f:
                            csp_data = f.read()
                        csp_source, csp_aligned = "generated", True
                        _drop(out)
                        _drop(out + ".head.json")
                    else:
                        log.warning(f"CSP generation failed for {costume_code}")
                except Exception as e:
                    log.warning(f"CSP generation error for {costume_code}: {e}")
                # A costume the fighter's own camera cannot see out of is framed
                # on its own geometry instead, so the portrait shows a character
                # rather than a patch of its surface.
                if not _shows_the_costume(csp_data, log):
                    size = None
                    try:
                        import io as _io

                        from PIL import Image as _Image
                        size = _Image.open(_io.BytesIO(csp_data)).size
                    except Exception:
                        size = None
                    framed = _fitted_portrait(dat_path, size, log)
                    if framed:
                        # Still 'generated' provenance -- we rendered it -- but no
                        # longer the vanilla pose, which `csp_aligned` carries.
                        csp_data, csp_aligned = framed, False
                        log.info(f"portrait: {costume_code} framed on its own geometry")

        # ---- stock -----------------------------------------------------------
        if stock_data is None:
            if not allow_stock_gen:
                # Fast path (ISO-scan bulk import): skip the texture-diff /
                # head-shot stock generator entirely. Nana still copies Popo's
                # icon; everyone else falls straight back to the vanilla stock
                # for this costume (the character's default colour if the exact
                # slot has none).
                if is_nana:
                    stock_data = popo_stock
                    stock_source = "copied_from_popo" if popo_stock else "missing"
                elif character in _GW_NAMES:
                    data, stock_source = _vanilla_stock(character, costume_code)
                    if data and gw_colors and gw_colors.get('fill') is not None:
                        stock_data = recolor_gw_stock_rgb(data, gw_colors['fill'])
                    else:
                        stock_data = recolor_gw_stock(data, color_index) if data else None
                else:
                    stock_data, stock_source = _vanilla_stock(character, costume_code)
            else:
                # only our OWN render (vanilla pose => pixel-aligned) may feed the
                # csp-diff path; community/custom CSPs must not, and neither may
                # the geometry-framed fallback, which is another camera entirely.
                aligned_csp = csp_data if csp_aligned else None
                stock_data, stock_source, _ = build_stock(
                    character, costume_code, dat_data, dat_path=dat_path,
                    aligned_csp=aligned_csp, is_nana=is_nana, popo_stock=popo_stock,
                    color_index=color_index, gw_colors=gw_colors,
                    vanilla_fallback=True, log=log)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        "csp": csp_data, "csp_source": csp_source or "missing",
        "stock": stock_data, "stock_source": stock_source or "missing",
    }


def _draws_own_textures(dat_data: bytes, dat_path: str | None = None) -> bool:
    """Whether the costume's model draws images (datprobe.samples_textures):
    vanilla Mr. Game & Watch never does, a model imported onto him always."""
    from shared.rendering.datprobe import samples_textures
    if dat_path is not None:
        return samples_textures(dat_path)
    scratch = tempfile.mkdtemp(prefix="gw_probe_")
    try:
        path = os.path.join(scratch, "costume.dat")
        with open(path, "wb") as f:
            f.write(dat_data)
        return samples_textures(path)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _drop(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
