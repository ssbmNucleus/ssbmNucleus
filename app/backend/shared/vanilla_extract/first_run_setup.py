"""
First-run setup module for extracting vanilla assets from user's Melee ISO.

This module handles:
1. Extracting the user's vanilla Melee 1.02 ISO using mexcli
2. Reading fighter JSONs to get asset mappings
3. Copying DATs, CSPs, stocks, CSS icons to utility/assets/vanilla/
4. Persisting the CSP renderer's vanilla references in storage/test-base/files/
5. Copying stage images to utility/assets/stages/
6. Seeding each character's pristine voice/SFX bank into the vault
   (storage/<Character>/sounds/original.ssm) so sound packs can be
   created without opening a project
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
import logging
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import Callable, Optional

import file_retry
from core.child_procs import own
from core.config import HSDRAW_EXE, STORAGE_PATH, get_subprocess_args
from core.child_env import child_environment

logger = logging.getLogger(__name__)


class FirstRunSetup:
    """Handles first-run setup: extracting vanilla assets from user's Melee ISO."""

    BUILTIN_GIGA_SLUG = "giga-bowser"
    BUILTIN_GIGA_NAME = "Giga Bowser"
    BUILTIN_GIGA_FIGHTER_JSON = "031.json"
    BUILTIN_GIGA_FIGHTER_INDEX = 31
    BUILTIN_GIGA_COSTUMES = (
        {"code": "Nr", "name": "Normal", "regions": {}},
        {
            "code": "Re",
            "name": "Red",
            "regions": {
                "skin": {"hue": 18, "saturation": 62},
                "shell": {"hue": 350, "saturation": 72},
                "fur": {"hue": 8, "saturation": 82},
            },
        },
        {
            "code": "Bu",
            "name": "Blue",
            "regions": {
                "skin": {"hue": 210, "saturation": 46},
                "shell": {"hue": 232, "saturation": 76},
                "fur": {"hue": 190, "saturation": 70},
            },
        },
        {
            "code": "Gr",
            "name": "Green",
            "regions": {
                "skin": {"hue": 108, "saturation": 52},
                "shell": {"hue": 142, "saturation": 78},
                "fur": {"hue": 78, "saturation": 70},
            },
        },
    )

    # Bump when the staged layout changes so old stages are re-made rather than
    # fed to a build step that no longer understands them.
    BUILTIN_STAGE_VERSION = 1

    # Fighter-file keys re-injected into the exported package from the project's
    # own file bank (the export leaves the demo/result/Kirby-hat data out).
    BUILTIN_FIGHTER_FILE_KEYS = (
        "fighterDataPath", "animFile", "demoFile", "rstAnimFile",
        "effectFile", "kirbyCapFileName", "kirbyEffectFile",
    )

    # Original fighters (indices 0-26 in fighter JSONs)
    # Includes: Mario(0), Fox(1)...Ganondorf(25), Roy(26)
    # Note: Nana(11) is included as separate from Popo/Ice Climbers
    VANILLA_FIGHTER_COUNT = 27
    # Giga Bowser is not on the normal CSS roster, but the app seeds him as a
    # built-in custom fighter and the CSP renderer needs his ftData as well.
    CSP_REFERENCE_EXTRA_FIGHTER_INDICES = (31,)
    CSP_REFERENCE_MANIFEST_VERSION = 1
    CSP_REFERENCE_EXPECTED_FILE_COUNT = 152
    CSP_REFERENCE_FTDATA_COUNT = 28
    CSP_REFERENCE_COSTUME_COUNT = 124

    # Stage icon mappings (ISO assets/sss/ -> utility/assets/stages/)
    STAGE_ICONS = {
        "icon_036.png": "pokemon stadium.png",
        "icon_012.png": "yoshis story.png",
        "icon_016.png": "fountain of dreams.png",
        "icon_050.png": "final destination.png",
        "icon_048.png": "battlefield.png",
        "icon_052.png": "dreamland.png"
    }

    # Characters whose CSPs should NOT be overwritten (kept in git)
    # Sheik has custom CSPs since vanilla Melee doesn't have separate Sheik portraits
    PRESERVE_CSP_CHARACTERS = ["Sheik"]

    # Characters whose costume folders legitimately have no csp.png after a
    # successful setup. Nana's fighter JSON carries no per-costume CSP refs
    # (she shares Popo's portraits), so her folders hold only the DATs.
    CSP_LESS_CHARACTERS = {"Nana"}

    # Asset overrides for characters with incorrect mappings in fighter JSONs
    # Mr. Game & Watch's JSON points to wrong CSP/stock indices
    ASSET_OVERRIDES = {
        "Mr. Game & Watch": {
            "PlGwNr": {
                "csp": "csp/csp_015",
                "icon": "icons/ft_109"
            }
        }
    }

    # Expected size of extracted ISO in bytes (~1.4GB for vanilla Melee)
    EXPECTED_EXTRACTION_SIZE = 1_400_000_000

    # Menu sound mappings: index in main.ssm -> filename
    # These are the UI sounds used in the app
    MENU_SOUNDS = {
        115: "new_skin",
        116: "big_achievement",
        117: "back",
        118: "start",
        119: "tick",
        120: "error",
        127: "click",
        135: "camera_click",
        216: "major_error"
    }

    def __init__(self, project_root: Path, mexcli_path: Path,
                 storage_path: Optional[Path] = None):
        """
        Initialize the first-run setup handler.

        Args:
            project_root: Root path of the project
            mexcli_path: Path to mexcli executable
        """
        self.project_root = project_root
        self.mexcli_path = mexcli_path
        self.hsdraw_path = Path(HSDRAW_EXE)
        self.storage_path = Path(storage_path) if storage_path is not None else STORAGE_PATH
        self.csp_reference_dir = self.storage_path / "test-base" / "files"
        self.csp_reference_manifest = (
            self.storage_path / "test-base" / "csp-references.json"
        )
        self.vanilla_dir = project_root / "utility" / "assets" / "vanilla"
        self.stages_dir = project_root / "utility" / "assets" / "stages"
        self.sounds_dir = project_root / "utility" / "assets" / "vanilla" / "sounds"

        # Detect bundled resources directory (for production builds).
        # READ-ONLY: bundled Sheik PNGs and menu sounds are copied OUT of it into
        # the data folder. Setup never writes inside the install: a macOS bundle's
        # signature breaks, the Linux AppImage is read-only, and an update
        # replaces the folder. (Until 0.9.0 phase 4 copied 27 vanilla Pl*Nr.dat
        # into resources/utility/tools/processor/csp_data; nothing ever read them.
        # The renderer's vanilla DATs are the reference bank in csp_reference_dir.)
        if getattr(sys, 'frozen', False):
            exe_path = Path(sys.executable)
            self.bundled_resources_dir = exe_path.parent.parent  # resources/
        else:
            self.bundled_resources_dir = None

    def _csp_reference_bank_status(self) -> dict:
        """Validate the user-derived flat reference bank used by generate_csp.

        New setups carry a manifest naming every copied file. The count fallback
        recognizes dev/legacy banks created before the manifest existed, without
        forcing those users through setup again when all 152 references are
        already present.
        """
        try:
            if self.csp_reference_manifest.is_file():
                manifest = json.loads(
                    self.csp_reference_manifest.read_text(encoding="utf-8")
                )
                names = manifest.get("files") or []
                if (manifest.get("version") != self.CSP_REFERENCE_MANIFEST_VERSION
                        or len(names) != self.CSP_REFERENCE_EXPECTED_FILE_COUNT):
                    return {
                        "complete": False,
                        "details": "CSP reference manifest is incomplete or outdated",
                    }
                missing = [name for name in names
                           if not (self.csp_reference_dir / name).is_file()]
                if missing:
                    return {
                        "complete": False,
                        "details": (f"CSP reference bank is missing {len(missing)} file(s), "
                                    f"including {missing[0]}"),
                    }
                return {"complete": True, "details": f"All {len(names)} CSP references present"}

            if not self.csp_reference_dir.is_dir():
                return {"complete": False, "details": "CSP reference bank does not exist"}

            ftdata = 0
            costumes = 0
            for path in self.csp_reference_dir.glob("Pl*.dat"):
                if re.fullmatch(r"Pl[A-Za-z]{2}", path.stem):
                    ftdata += 1
                elif (re.fullmatch(r"Pl[A-Za-z]{4}", path.stem)
                      and not path.stem.endswith("AJ")):
                    costumes += 1
            if (ftdata >= self.CSP_REFERENCE_FTDATA_COUNT
                    and costumes >= self.CSP_REFERENCE_COSTUME_COUNT):
                return {
                    "complete": True,
                    "details": f"Legacy CSP reference bank present ({ftdata} fighter, {costumes} costume)",
                }
            return {
                "complete": False,
                "details": (f"Found {ftdata}/{self.CSP_REFERENCE_FTDATA_COUNT} fighter and "
                            f"{costumes}/{self.CSP_REFERENCE_COSTUME_COUNT} costume CSP references"),
            }
        except Exception as e:
            return {"complete": False, "details": f"Could not validate CSP references: {e}"}

    def check_setup_needed(self) -> dict:
        """
        Check if first-run setup is needed.

        Returns:
            dict with 'complete' bool and 'details' about what's missing
        """
        if not self.vanilla_dir.exists():
            return {
                'complete': False,
                'reason': 'vanilla_dir_missing',
                'details': 'Vanilla assets directory does not exist'
            }

        # Check for at least some character folders
        # Exclude non-character directories: custom_poses, and the menu-sound
        # bank that _copy_bundled_sounds/_extract_menu_sounds place at
        # vanilla/sounds (it has no Pl* costume folders).
        excluded_dirs = {'custom_poses', 'sounds'}
        char_folders = [d for d in self.vanilla_dir.iterdir() if d.is_dir() and d.name not in excluded_dirs]
        if len(char_folders) < self.VANILLA_FIGHTER_COUNT:
            return {
                'complete': False,
                'reason': 'insufficient_characters',
                'details': f'Found {len(char_folders)} character folders, expected {self.VANILLA_FIGHTER_COUNT}'
            }

        # Sample check: verify a few characters have proper structure.
        # Sorted, and CSP-less characters (Nana) skipped: iterdir order is
        # filesystem-dependent — NTFS is alphabetical, ext4 is hash order — and
        # on Linux Nana could land in this sample, making a completed setup
        # look forever incomplete (the AppImage re-ran first-run setup, ISO
        # extraction included, on every launch).
        sample_chars = sorted(
            (d for d in char_folders if d.name not in self.CSP_LESS_CHARACTERS),
            key=lambda d: d.name.lower())[:5]
        for char_dir in sample_chars:
            # Check for at least one costume subfolder with csp.png
            costume_dirs = sorted(
                (d for d in char_dir.iterdir() if d.is_dir() and d.name.startswith('Pl')),
                key=lambda d: d.name.lower())
            if not costume_dirs:
                return {
                    'complete': False,
                    'reason': 'missing_costumes',
                    'details': f'Character {char_dir.name} has no costume folders'
                }

            # Check first costume has required files
            first_costume = costume_dirs[0]
            if not (first_costume / 'csp.png').exists():
                return {
                    'complete': False,
                    'reason': 'missing_csp',
                    'details': f'Costume {first_costume.name} missing csp.png'
                }

        # Check stages
        if not self.stages_dir.exists():
            return {
                'complete': False,
                'reason': 'stages_dir_missing',
                'details': 'Stages directory does not exist'
            }

        stage_count = len(list(self.stages_dir.glob('*.png'))) + len(list(self.stages_dir.glob('*.jpg')))
        if stage_count < len(self.STAGE_ICONS):
            return {
                'complete': False,
                'reason': 'insufficient_stages',
                'details': f'Found {stage_count} stage images, expected {len(self.STAGE_ICONS)}'
            }

        csp_refs = self._csp_reference_bank_status()
        if not csp_refs['complete']:
            return {
                'complete': False,
                'reason': 'csp_references_missing',
                'details': csp_refs['details'],
            }

        return {
            'complete': True,
            'details': 'All vanilla assets present'
        }

    def _copy_bundled_sheik_assets(self) -> dict:
        """
        Copy bundled Sheik PNGs from resources to PROJECT_ROOT.

        Sheik has custom CSPs since vanilla Melee doesn't have separate Sheik portraits.
        These are bundled with the app and need to be copied to the user's writable
        directory before ISO extraction (which skips Sheik CSPs via PRESERVE_CSP_CHARACTERS).
        """
        if not self.bundled_resources_dir:
            # Not running as bundled exe, skip
            return {'success': True}

        bundled_sheik_dir = self.bundled_resources_dir / "utility" / "assets" / "vanilla" / "Sheik"
        if not bundled_sheik_dir.exists():
            logger.warning(f"Bundled Sheik assets not found at: {bundled_sheik_dir}")
            return {'success': True}  # Not fatal, continue anyway

        try:
            dest_sheik_dir = self.vanilla_dir / "Sheik"
            dest_sheik_dir.mkdir(parents=True, exist_ok=True)

            # Copy all PNG files (CSPs, stock icons, css_icon)
            copied_count = 0
            for src_file in bundled_sheik_dir.rglob("*.png"):
                # Preserve subdirectory structure (e.g., PlSkNr/csp.png)
                rel_path = src_file.relative_to(bundled_sheik_dir)
                dest_file = dest_sheik_dir / rel_path
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dest_file)
                copied_count += 1

            logger.info(f"Copied {copied_count} bundled Sheik PNGs to {dest_sheik_dir}")
            return {'success': True, 'copied': copied_count}

        except Exception as e:
            logger.error(f"Failed to copy bundled Sheik assets: {e}")
            return {'success': False, 'error': str(e)}

    def _copy_bundled_sounds(self) -> dict:
        """
        Copy bundled menu sounds from resources to PROJECT_ROOT.

        Menu sounds are bundled with the app for reliability instead of
        extracting them from the ISO at runtime.
        """
        if not self.bundled_resources_dir:
            # Not running as bundled exe, skip
            return {'success': True}

        bundled_sounds_dir = self.bundled_resources_dir / "utility" / "assets" / "vanilla" / "sounds"
        if not bundled_sounds_dir.exists():
            logger.warning(f"Bundled sounds not found at: {bundled_sounds_dir}")
            return {'success': True}  # Not fatal, continue anyway

        try:
            self.sounds_dir.mkdir(parents=True, exist_ok=True)

            # Copy all WAV files
            copied_count = 0
            for src_file in bundled_sounds_dir.glob("*.wav"):
                dest_file = self.sounds_dir / src_file.name
                shutil.copy2(src_file, dest_file)
                copied_count += 1

            logger.info(f"Copied {copied_count} bundled sounds to {self.sounds_dir}")
            return {'success': True, 'copied': copied_count}

        except Exception as e:
            logger.error(f"Failed to copy bundled sounds: {e}")
            return {'success': False, 'error': str(e)}

    def _read_metadata(self) -> dict:
        metadata_file = self.storage_path / "metadata.json"
        if not metadata_file.exists():
            return {
                "version": "1.0",
                "characters": {},
                "stages": {},
                "custom_stages": [],
                "custom_characters": [],
            }
        with open(metadata_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("version", "1.0")
        data.setdefault("characters", {})
        data.setdefault("stages", {})
        data.setdefault("custom_stages", [])
        data.setdefault("custom_characters", [])
        return data

    def _write_metadata(self, metadata: dict) -> None:
        metadata_file = self.storage_path / "metadata.json"
        metadata_file.parent.mkdir(parents=True, exist_ok=True)
        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

    @staticmethod
    def _zip_with_replacements(zip_path: Path, replacements: dict[str, bytes]) -> None:
        tmp_path = zip_path.with_suffix(zip_path.suffix + ".tmp")
        written = set()
        with zipfile.ZipFile(zip_path, "r") as src, zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as dst:
            existing = {item.filename for item in src.infolist()}
            for item in src.infolist():
                data = replacements.get(item.filename)
                if data is None:
                    data = src.read(item.filename)
                else:
                    written.add(item.filename)
                dst.writestr(item, data)
            for name, data in replacements.items():
                if name not in written and name not in existing:
                    dst.writestr(name, data)
        file_retry.replace(tmp_path, zip_path)

    @staticmethod
    def _fit_png(source_path: Path, size: tuple[int, int]) -> bytes:
        from io import BytesIO
        from PIL import Image

        with Image.open(source_path) as source:
            img = source.convert("RGBA")
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)
        resampling = getattr(Image, "Resampling", Image)
        img.thumbnail(size, getattr(resampling, "LANCZOS", Image.BICUBIC))
        canvas = Image.new("RGBA", size, (0, 0, 0, 0))
        x = (size[0] - img.width) // 2
        y = (size[1] - img.height) // 2
        canvas.alpha_composite(img, (x, y))
        buf = BytesIO()
        canvas.save(buf, format="PNG")
        return buf.getvalue()

    @staticmethod
    def _make_text_banner(size: tuple[int, int], text: str) -> bytes:
        from io import BytesIO
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        font = None
        for font_name in ("arialbd.ttf", "arial.ttf"):
            try:
                font = ImageFont.truetype(font_name, max(8, size[1] - 8))
                break
            except Exception:
                font = None
        if font is None:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = max(0, (size[0] - text_w) // 2)
        y = max(0, (size[1] - text_h) // 2 - 1)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, 220))
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    @staticmethod
    def _resolve_asset_png(assets_dir: Path, ref: str | None) -> Path | None:
        if not ref:
            return None
        path = assets_dir / (ref.replace("\\", "/") + ".png")
        return path if path.exists() else None

    def _bundled_giga_icon(self) -> Path | None:
        # Giga has no in-game CSS icon to derive, so ship a hand-made one. The
        # asset lives at backend/assets/builtin/<slug>/icon.png. In a frozen
        # build self.project_root is the user-data dir (LocalAppData), NOT the
        # install, so resolve from the PyInstaller bundle (_MEIPASS) there;
        # fall back to the source tree path for dev.
        rel = Path("backend") / "assets" / "builtin" / self.BUILTIN_GIGA_SLUG / "icon.png"
        candidates = []
        if getattr(sys, "frozen", False):
            candidates.append(Path(sys._MEIPASS) / rel)
        candidates.append(self.project_root / rel)
        for path in candidates:
            if path.exists():
                return path
        return None

    def _giga_bowser_seed_current(self, char_dir: Path) -> bool:
        zip_path = char_dir / "fighter.zip"
        fighter_json_path = char_dir / "fighter.json"
        if not zip_path.exists() or not fighter_json_path.exists():
            return False

        expected_dat_files = {
            f"PlGk{spec['code']}.dat" for spec in self.BUILTIN_GIGA_COSTUMES
        }
        expected_zip_files = {
            f"PlGk{spec['code']}.zip" for spec in self.BUILTIN_GIGA_COSTUMES
        }

        try:
            with open(fighter_json_path, "r", encoding="utf-8") as f:
                fighter_data = json.load(f)
            current_dat_files = {
                ((costume.get("file") or {}).get("fileName") or "")
                for costume in fighter_data.get("costumes", [])
            }
            if not expected_dat_files.issubset(current_dat_files):
                return False
            if (
                fighter_data.get("redCostumeIndex") != 1
                or fighter_data.get("blueCostumeIndex") != 2
                or fighter_data.get("greenCostumeIndex") != 3
            ):
                return False

            with zipfile.ZipFile(zip_path, "r") as zf:
                names = set(zf.namelist())
                if not expected_zip_files.issubset(names):
                    return False
                for zip_name in expected_zip_files:
                    with zipfile.ZipFile(zf.open(zip_name), "r") as costume_zip:
                        inner_names = set(costume_zip.namelist())
                        stem = Path(zip_name).stem
                        if f"{stem}.dat" not in inner_names:
                            return False

            bundled_icon = self._bundled_giga_icon()
            current_icon = char_dir / "css_icon.png"
            if bundled_icon and (
                not current_icon.exists()
                or current_icon.read_bytes() != bundled_icon.read_bytes()
            ):
                return False
        except Exception:
            return False

        return True

    def _patch_giga_bowser_fighter_data(
        self,
        fighter_data: dict,
        bowser_data: dict | None,
        costume_specs: list[dict] | None = None,
    ) -> dict:
        data = json.loads(json.dumps(fighter_data))
        data["name"] = self.BUILTIN_GIGA_NAME
        data["seriesID"] = 11
        data["targetTestStage"] = (bowser_data or {}).get("targetTestStage", 42)
        data["classicTrophyId"] = (bowser_data or {}).get("classicTrophyId", 30)
        data["adventureTrophyId"] = (bowser_data or {}).get("adventureTrophyId", 31)
        data["allStarTrophyId"] = (bowser_data or {}).get("allStarTrophyId", 32)
        data["racetoTheFinishTime"] = (bowser_data or {}).get("racetoTheFinishTime", 52)
        data["resultScreenScale"] = 0.35
        data["endingScreenScale"] = 0.2
        costume_specs = costume_specs or [self.BUILTIN_GIGA_COSTUMES[0]]
        code_to_index = {spec["code"]: i for i, spec in enumerate(costume_specs)}
        data["redCostumeIndex"] = code_to_index.get("Re", 0)
        data["blueCostumeIndex"] = code_to_index.get("Bu", 0)
        data["greenCostumeIndex"] = code_to_index.get("Gr", 0)

        bowser_files = (bowser_data or {}).get("files") or {}
        files = data.setdefault("files", {})
        for key in (
            "demoFile", "demoWait", "demoResult", "demoIntro", "demoEnding",
            "rstAnimFile", "rstAnimCount", "kirbyCapFileName", "kirbyCapSymbol",
            "kirbyEffectFile", "kirbyEffectSymbol",
        ):
            if bowser_files.get(key) not in (None, ""):
                files[key] = bowser_files[key]

        data["assets"] = {
            "cssIcon": "css\\icon",
            "resultBannerBig": "rst\\big_banner",
            "resultSmallBig": "rst\\small_banner",
        }
        base_costume = json.loads(json.dumps((data.get("costumes") or [{}])[0]))
        base_file = base_costume.setdefault("file", {})
        base_file.setdefault("visibilityIndex", 0)
        base_file.setdefault("jointSymbol", "PlyGkoopa5K_Share_joint")
        base_file.setdefault("materialSymbol", "PlyGkoopa5K_Share_matanim_joint")
        costumes = []
        for index, spec in enumerate(costume_specs):
            costume = json.loads(json.dumps(base_costume))
            costume["name"] = spec["name"]
            costume["colorSmashGroup"] = int(base_costume.get("colorSmashGroup", -132)) - index
            file_info = costume.setdefault("file", {})
            file_info["visibilityIndex"] = 0
            file_info["fileName"] = f"PlGk{spec['code']}.dat"
            file_info["jointSymbol"] = "PlyGkoopa5K_Share_joint"
            file_info["materialSymbol"] = "PlyGkoopa5K_Share_matanim_joint"
            costume["icon"] = None
            costume["csp"] = None
            costumes.append(costume)
        data["costumes"] = costumes
        return data

    def _render_giga_csp(self, dat_path: Path) -> Path | None:
        try:
            import generate_csp as csp_renderer
        except Exception as e:
            logger.warning(f"Giga Bowser CSP renderer unavailable: {e}")
            return None

        try:
            if self.hsdraw_path.exists():
                csp_renderer.HSDRAW_EXE = str(self.hsdraw_path)
            rendered = csp_renderer.generate_csp(str(dat_path))
            if rendered and Path(rendered).exists():
                return Path(rendered)
        except Exception as e:
            logger.warning(f"Giga Bowser CSP render failed: {e}")
        return None

    def _make_giga_stock(self, dat_path, csp_path):
        """Proper Melee-style stock icon for a Giga costume: bind-pose head
        shot + a FIXED face crop around the projected head bone. The generic
        stock_gen silhouette crop cuts at the neck pinch, but Giga has no
        pinch (his head merges into the shell), so it kept the whole body —
        a full-body 24x24 blob. The face box below (in head-bone-relative
        coords, tuned on the scale-2 render) matches vanilla Bowser's
        face-fills-the-frame stock composition. Falls back to a plain CSP
        downscale only if the head shot fails."""
        if dat_path and Path(dat_path).exists():
            try:
                from io import BytesIO

                from PIL import Image

                from generate_csp import generate_head_shot
                from shared.rendering.stock_gen import _pixelize_icon
                shot, head = generate_head_shot(str(dat_path))
                if shot and head and not head.get("behindCamera"):
                    # scale the tuned scale-2 box (hx-44, hy-46, hx+48, hy+42)
                    # by the actual render size so any --scale works
                    s = head.get("width", 272) / 272.0
                    hx, hy = head["x"], head["y"]
                    box = (int(hx - 44 * s), int(hy - 46 * s),
                           int(hx + 48 * s), int(hy + 42 * s))
                    img = Image.open(shot).convert("RGBA")
                    icon = _pixelize_icon(img.crop(box), resample=Image.BOX)
                    buf = BytesIO()
                    Image.fromarray(icon.astype("uint8")).save(buf, "PNG")
                    return buf.getvalue()
            except Exception as e:
                logger.warning(f"Giga Bowser stock render failed, using CSP downscale: {e}")
        if csp_path and csp_path.exists():
            return self._fit_png(csp_path, (24, 24))
        return None

    @staticmethod
    def _costume_zip_with_dat(
        base_zip_bytes: bytes,
        dat_name: str,
        dat_bytes: bytes,
        csp_bytes: bytes | None = None,
        stock_bytes: bytes | None = None,
    ) -> bytes:
        from io import BytesIO

        out = BytesIO()
        wrote_dat = False
        wrote_csp = False
        wrote_stock = False
        with zipfile.ZipFile(BytesIO(base_zip_bytes), "r") as src, \
                zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                basename = Path(item.filename).name.lower()
                if basename.endswith(".dat"):
                    if not wrote_dat:
                        dst.writestr(dat_name, dat_bytes)
                        wrote_dat = True
                    continue
                if basename == "csp.png":
                    if csp_bytes is not None:
                        dst.writestr("csp.png", csp_bytes)
                        wrote_csp = True
                    continue
                if basename == "stc.png":
                    if stock_bytes is not None:
                        dst.writestr("stc.png", stock_bytes)
                        wrote_stock = True
                    continue
                dst.writestr(item, src.read(item.filename))
            if not wrote_dat:
                dst.writestr(dat_name, dat_bytes)
            if csp_bytes is not None and not wrote_csp:
                dst.writestr("csp.png", csp_bytes)
            if stock_bytes is not None and not wrote_stock:
                dst.writestr("stc.png", stock_bytes)
        return out.getvalue()

    def _run_hsdraw_texture(self, args: list[str | Path], context: str) -> str:
        if not self.hsdraw_path.exists():
            raise FileNotFoundError(f"CSP renderer not found at {self.hsdraw_path}")
        result = subprocess.run(
            [str(self.hsdraw_path), *[str(arg) for arg in args]],
            capture_output=True,
            text=True,
            cwd=str(self.project_root),
            **get_subprocess_args(),
        )
        if result.returncode != 0:
            output = "\n".join(
                part for part in (result.stdout, result.stderr) if part
            ).strip()
            tail = output[-2000:] if output else f"exit code {result.returncode}"
            raise RuntimeError(f"{context} failed: {tail}")
        return result.stdout or ""

    def _make_giga_recolor_dat(self, base_dat: Path, out_dat: Path, spec: dict) -> Path:
        import uuid
        import numpy as np
        from PIL import Image
        from shared.rendering import compose as compose_mod

        # Bundled asset: in a frozen build self.project_root is the user-data dir,
        # so resolve from the PyInstaller bundle (_MEIPASS) there. (Same gotcha as
        # _bundled_giga_icon; without this Giga recolors silently fail in the
        # installed build and Giga ends up with only the Normal costume.)
        rmrel = Path("backend") / "assets" / "texture_regions" / "Bowser.json"
        region_map_path = (
            Path(sys._MEIPASS) / rmrel if getattr(sys, "frozen", False)
            else self.project_root / rmrel
        )
        if not region_map_path.exists():
            region_map_path = self.project_root / rmrel
        with open(region_map_path, "r", encoding="utf-8") as f:
            region_map = json.load(f)
        regions = region_map.get("regions") or {}
        protected = set(region_map.get("protected") or [])

        out_dat.parent.mkdir(parents=True, exist_ok=True)
        work_dir = out_dat.parent / f"{out_dat.stem}_{uuid.uuid4().hex[:8]}_textures"
        work_dir.mkdir(parents=True, exist_ok=True)
        root_joint = "PlyGkoopa5K_Share_joint"
        current_dat = base_dat
        selected_textures = []
        seen_indexes = set()
        for region, params in (spec.get("regions") or {}).items():
            for index in regions.get(region, []):
                index = int(index)
                if index in protected or index in seen_indexes:
                    continue
                selected_textures.append((region, index, params))
                seen_indexes.add(index)

        changed = 0
        try:
            for order, (region, index, params) in enumerate(selected_textures):
                exported_png = work_dir / f"{order:03d}_{index:03d}.png"
                tinted_png = work_dir / f"{order:03d}_{index:03d}_tinted.png"
                next_dat = work_dir / f"{out_dat.stem}_step_{changed + 1:03d}.dat"
                try:
                    self._run_hsdraw_texture(
                        ["--texture", "export", current_dat, root_joint, index, exported_png],
                        f"Giga Bowser {spec['name']} texture {index} export",
                    )
                    with Image.open(exported_png) as image:
                        arr = np.array(image.convert("RGBA"))
                    mask = compose_mod.build_mask(arr)
                    result = compose_mod.tint(
                        arr,
                        mask,
                        hue=float(params["hue"]),
                        saturation=float(params.get("saturation", 60)),
                    )
                    if result is None:
                        continue
                    Image.fromarray(np.asarray(result).astype("uint8"), "RGBA").save(tinted_png)
                    self._run_hsdraw_texture(
                        ["--texture", "import", current_dat, root_joint, index, tinted_png, next_dat],
                        f"Giga Bowser {spec['name']} texture {index} import",
                    )
                    current_dat = next_dat
                    changed += 1
                except Exception as e:
                    logger.warning(
                        "Giga Bowser %s texture %s (%s) recolor skipped: %s",
                        spec["name"],
                        index,
                        region,
                        e,
                    )
            if changed == 0:
                raise RuntimeError(f"no Giga Bowser textures changed for {spec['name']}")
            shutil.copy2(current_dat, out_dat)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
        return out_dat

    def _builtin_stage_dir(self, slug: str) -> Path:
        """Where first-run setup parks the raw inputs for a built-in fighter
        until the user actually asks for it."""
        return self.storage_path / "builtin_seed" / slug

    def _giga_seed_state(self, force: bool = False) -> dict:
        """Whether Giga Bowser still needs seeding, and why not if he doesn't."""
        char_dir = self.storage_path / "custom_characters" / self.BUILTIN_GIGA_SLUG
        metadata = self._vault_metadata()
        existing = next(
            (
                c for c in metadata.get("custom_characters", [])
                if c.get("slug") == self.BUILTIN_GIGA_SLUG
                or c.get("name", "").lower() == self.BUILTIN_GIGA_NAME.lower()
            ),
            None,
        )
        if existing and (char_dir / "fighter.zip").exists() and not force:
            existing_is_builtin = (
                existing.get("builtin")
                or existing.get("source") == "builtin"
                or existing.get("slug") == self.BUILTIN_GIGA_SLUG
            )
            if not existing_is_builtin:
                return {"needed": False, "reason": "custom_character_conflict", "entry": existing}
            if self._giga_bowser_seed_current(char_dir):
                return {"needed": False, "reason": "already_present", "entry": existing}
        return {"needed": True, "reason": "", "entry": existing}

    def stage_builtin_giga_bowser(self, temp_dir: Path, force: bool = False) -> dict:
        """Copy what the Giga Bowser seed needs out of the temporary mexcli
        project — without rendering anything.

        The renders (4 CSPs, 3 texture recolors, 4 stock icons) added minutes to
        first-run setup for a character most users never open. Setup now only
        parks a few MB in ``storage/builtin_seed/``; the Custom Characters page
        shows Giga greyed out and finishes the job on the first click
        (``build_builtin_character``).
        """
        state = self._giga_seed_state(force)
        if not state["needed"]:
            return {"success": True, "staged": False, "reason": state["reason"]}

        project_path = temp_dir / "temp_project.mexproj"
        if not project_path.exists():
            project_path = temp_dir / "project.mexproj"
        fighters_dir = temp_dir / "data" / "fighters"
        assets_dir = temp_dir / "assets"
        files_dir = temp_dir / "files"
        giga_json = fighters_dir / self.BUILTIN_GIGA_FIGHTER_JSON
        if not project_path.exists() or not giga_json.exists():
            return {"success": False, "error": "Giga Bowser fighter data not found in extracted project"}

        stage_dir = self._builtin_stage_dir(self.BUILTIN_GIGA_SLUG)
        shutil.rmtree(stage_dir, ignore_errors=True)
        (stage_dir / "files").mkdir(parents=True, exist_ok=True)
        (stage_dir / "assets").mkdir(parents=True, exist_ok=True)

        try:
            zip_path = stage_dir / "fighter.zip"
            cmd = [
                str(self.mexcli_path),
                "export-fighter",
                str(project_path),
                str(self.BUILTIN_GIGA_FIGHTER_INDEX),
                str(zip_path),
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.project_root),
                **get_subprocess_args(),
            )
            if result.returncode != 0 or not zip_path.exists():
                shutil.rmtree(stage_dir, ignore_errors=True)
                return {
                    "success": False,
                    "error": result.stderr or result.stdout or "mexcli export-fighter failed",
                }

            shutil.copy2(giga_json, stage_dir / "fighter.json")
            bowser_json = fighters_dir / "005.json"
            bowser_data = None
            if bowser_json.exists():
                shutil.copy2(bowser_json, stage_dir / "base_fighter.json")
                with open(bowser_json, "r", encoding="utf-8") as f:
                    bowser_data = json.load(f)

            with open(giga_json, "r", encoding="utf-8") as f:
                fighter_data = json.load(f)
            # The build step injects these from the file bank, and it works off
            # the PATCHED fighter data — which borrows Bowser's demo/result/
            # Kirby-hat files — so stage both name sets or those entries go
            # missing from the package.
            patched = self._patch_giga_bowser_fighter_data(fighter_data, bowser_data)
            wanted = ["PlGkNr.dat"]
            wanted += [
                name for data in (fighter_data, patched)
                for name in (
                    (data.get("files") or {}).get(key)
                    for key in self.BUILTIN_FIGHTER_FILE_KEYS
                ) if name
            ]
            for name in dict.fromkeys(wanted):
                source = files_dir / name
                if source.exists():
                    shutil.copy2(source, stage_dir / "files" / name)
            if not (stage_dir / "files" / "PlGkNr.dat").exists():
                shutil.rmtree(stage_dir, ignore_errors=True)
                return {"success": False, "error": "PlGkNr.dat missing from extracted project"}

            for ref, dest_name in (("csp\\csp_025", "csp_fallback.png"),
                                   ("css\\icon_005", "icon_fallback.png")):
                source = self._resolve_asset_png(assets_dir, ref)
                if source:
                    shutil.copy2(source, stage_dir / "assets" / dest_name)

            (stage_dir / "stage.json").write_text(json.dumps({
                "version": self.BUILTIN_STAGE_VERSION,
                "slug": self.BUILTIN_GIGA_SLUG,
                "name": self.BUILTIN_GIGA_NAME,
                "costume_count": len(self.BUILTIN_GIGA_COSTUMES),
                "created": datetime.now().isoformat(),
            }, indent=2), encoding="utf-8")
        except Exception as e:
            shutil.rmtree(stage_dir, ignore_errors=True)
            logger.error(f"Staging Giga Bowser failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

        logger.info(f"Staged built-in Giga Bowser for on-demand setup at {stage_dir}")
        return {"success": True, "staged": True}

    def builtin_pending_characters(self) -> list[dict]:
        """Built-in fighters that are staged but not yet built — the greyed-out
        cards on the Custom Characters page."""
        pending = []
        stage_dir = self._builtin_stage_dir(self.BUILTIN_GIGA_SLUG)
        if not (stage_dir / "stage.json").is_file() or not (stage_dir / "fighter.zip").is_file():
            return pending
        try:
            stage = json.loads((stage_dir / "stage.json").read_text(encoding="utf-8"))
        except Exception:
            return pending
        if stage.get("version") != self.BUILTIN_STAGE_VERSION:
            return pending
        if not self._giga_seed_state()["needed"]:
            return pending
        pending.append({
            "slug": self.BUILTIN_GIGA_SLUG,
            "name": self.BUILTIN_GIGA_NAME,
            "costume_count": stage.get("costume_count", len(self.BUILTIN_GIGA_COSTUMES)),
            "builtin": True,
            "pending_setup": True,
            "has_css_icon": self._bundled_giga_icon() is not None,
        })
        return pending

    def build_builtin_character(self, slug: str, progress_callback=None, *, job=None) -> dict:
        """Render and install a staged built-in fighter. Slow (minutes) — call
        it from a shared background job, never inline in a request."""
        if slug != self.BUILTIN_GIGA_SLUG:
            return {"success": False, "error": f"Unknown built-in character '{slug}'"}
        stage_dir = self._builtin_stage_dir(slug)
        # The staged inputs are kept after a build (a few MB). They can only be
        # produced from the extracted vanilla project during first-run setup, so
        # deleting them made a deleted Giga Bowser impossible to build again.
        # builtin_pending_characters() hides the card while he is installed.
        state = self._giga_seed_state()
        if not state["needed"]:
            return {"success": True, "seeded": False, "reason": state["reason"]}
        if not (stage_dir / "fighter.zip").is_file():
            return {"success": False, "error": "Built-in character is not staged; re-run setup"}
        return self._build_giga_from_stage(stage_dir, progress_callback, job=job)

    def _build_giga_from_stage(self, stage_dir: Path, progress_callback=None, *, job=None) -> dict:
        """Render Giga Bowser's costumes and install him into the vault."""
        if job is not None:
            recolor_dir = Path(tempfile.gettempdir()) / f'giga_recolors_{job.id}'
            job.own('recolors', str(recolor_dir))
            recolor_dir.mkdir(parents=True, exist_ok=True)
        else:
            recolor_dir = Path(tempfile.mkdtemp(prefix='giga_recolors_'))
        try:
            return self._build_giga(stage_dir, recolor_dir, progress_callback)
        finally:
            if job is None:
                shutil.rmtree(recolor_dir, ignore_errors=True)

    def _build_giga(self, stage_dir: Path, recolor_dir: Path,
                    progress_callback=None) -> dict:
        n_costumes = len(self.BUILTIN_GIGA_COSTUMES)

        def _seed_progress(pct, message, done=0):
            # Keep the bar visibly moving — the CSP/stock renders below are slow
            # and otherwise sit silently, which looks frozen.
            if progress_callback:
                progress_callback('seeding_builtins', int(pct), message, done, n_costumes)

        char_dir = self.storage_path / "custom_characters" / self.BUILTIN_GIGA_SLUG

        assets_dir = stage_dir / "assets"
        files_dir = stage_dir / "files"
        giga_json = stage_dir / "fighter.json"
        bowser_json = stage_dir / "base_fighter.json"

        with open(giga_json, "r", encoding="utf-8") as f:
            fighter_data = json.load(f)
        bowser_data = None
        if bowser_json.exists():
            with open(bowser_json, "r", encoding="utf-8") as f:
                bowser_data = json.load(f)
        char_dir.mkdir(parents=True, exist_ok=True)
        zip_path = char_dir / "fighter.zip"
        _seed_progress(4, 'Preparing Giga Bowser fighter…')
        shutil.copy2(stage_dir / "fighter.zip", zip_path)

        _seed_progress(10, 'Rendering Giga Bowser portrait…', 1)
        csp_path = self._render_giga_csp(files_dir / "PlGkNr.dat")
        if csp_path is None:
            fallback = assets_dir / "csp_fallback.png"
            csp_path = fallback if fallback.exists() else None

        costume_assets = [{
            "spec": self.BUILTIN_GIGA_COSTUMES[0],
            "dat_path": files_dir / "PlGkNr.dat",
            "csp_path": csp_path,
        }]
        # Place Giga's ftData (PlGk.dat) beside the recolor costume DATs. The CSP
        # renderer derives the per-character low-poly hide list from a sibling
        # Pl<XX>.dat (_find_ftdata); without it the recolor renders fall back to a
        # wrong scene hide list and drop Giga's hand. The Normal costume renders
        # from files_dir, which already has PlGk.dat as a sibling.
        giga_ftdata = files_dir / "PlGk.dat"
        if giga_ftdata.exists():
            shutil.copy2(giga_ftdata, recolor_dir / "PlGk.dat")
        recolor_specs = self.BUILTIN_GIGA_COSTUMES[1:]
        for ri, spec in enumerate(recolor_specs):
            # Recolor renders are the slow part — spread them across 10–70%.
            done = ri + 2
            pct = 10 + int(60 * (ri / max(1, len(recolor_specs))))
            _seed_progress(pct, f"Rendering {spec['name']} costume ({done}/{n_costumes})…", done)
            try:
                stem = f"PlGk{spec['code']}"
                dat_path = self._make_giga_recolor_dat(
                    files_dir / "PlGkNr.dat",
                    recolor_dir / f"{stem}.dat",
                    spec,
                )
                recolor_csp = self._render_giga_csp(dat_path)
                if recolor_csp is None:
                    recolor_csp = csp_path
                costume_assets.append({
                    "spec": spec,
                    "dat_path": dat_path,
                    "csp_path": recolor_csp,
                })
            except Exception as e:
                logger.warning(f"Giga Bowser {spec['name']} recolor failed: {e}")

        costume_specs = [asset["spec"] for asset in costume_assets]
        fighter_data = self._patch_giga_bowser_fighter_data(
            fighter_data, bowser_data, costume_specs)

        replacements: dict[str, bytes] = {
            "fighter.json": json.dumps(fighter_data, indent=2).encode("utf-8"),
            "big_banner.png": self._make_text_banner((256, 28), "GIGA BOWSER"),
            "small_banner.png": self._make_text_banner((120, 24), "GIGA"),
        }

        has_css_icon = False

        bundled_icon = self._bundled_giga_icon()

        if csp_path and csp_path.exists():
            icon_bytes = (
                bundled_icon.read_bytes()
                if bundled_icon
                else self._fit_png(csp_path, (64, 56))
            )
            replacements["icon.png"] = icon_bytes
            (char_dir / "css_icon.png").write_bytes(icon_bytes)
            has_css_icon = True
        else:
            staged_icon = assets_dir / "icon_fallback.png"
            fallback_icon = bundled_icon or (staged_icon if staged_icon.exists() else None)
            if fallback_icon:
                icon_bytes = fallback_icon.read_bytes()
                replacements["icon.png"] = icon_bytes
                (char_dir / "css_icon.png").write_bytes(icon_bytes)
                has_css_icon = True

        for key in self.BUILTIN_FIGHTER_FILE_KEYS:
            name = (fighter_data.get("files") or {}).get(key)
            if name:
                file_path = files_dir / name
                if file_path.exists():
                    replacements[name] = file_path.read_bytes()

        with zipfile.ZipFile(zip_path, "r") as zf:
            costume_zip = zf.read("PlGkNr.zip")

        costume_meta = []
        for index, asset in enumerate(costume_assets):
            spec = asset["spec"]
            # Stock-icon renders run here — spread across 70–95%.
            _seed_progress(70 + int(25 * (index / max(1, len(costume_assets)))),
                           f"Building {spec['name']} stock icon…", index + 1)
            stem = f"PlGk{spec['code']}"
            csp_asset_path = asset.get("csp_path")
            csp_bytes = csp_asset_path.read_bytes() if csp_asset_path and csp_asset_path.exists() else None
            stock_bytes = self._make_giga_stock(asset.get("dat_path"), csp_asset_path)
            if csp_bytes:
                (char_dir / f"csp_{index}.png").write_bytes(csp_bytes)
            if stock_bytes:
                (char_dir / f"stock_{index}.png").write_bytes(stock_bytes)
            replacements[f"{stem}.zip"] = self._costume_zip_with_dat(
                costume_zip,
                f"{stem}.dat",
                asset["dat_path"].read_bytes(),
                csp_bytes,
                stock_bytes,
            )
            costume_meta.append({
                "id": stem,
                "color": spec["name"],
                "filename": f"{stem}.zip",
                "dat_name": f"{stem}.dat",
                "has_csp": csp_bytes is not None,
                "has_stock": stock_bytes is not None,
            })

        _seed_progress(96, 'Finalizing Giga Bowser…', n_costumes)
        self._zip_with_replacements(zip_path, replacements)

        with open(char_dir / "fighter.json", "w", encoding="utf-8") as f:
            json.dump(fighter_data, f, indent=2)

        costumes_dir = char_dir / "costumes"
        costumes_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            for index, meta in enumerate(costume_meta):
                (costumes_dir / meta["filename"]).write_bytes(zf.read(meta["filename"]))
                if meta["has_csp"]:
                    shutil.copy2(char_dir / f"csp_{index}.png", costumes_dir / f"{meta['id']}_csp.png")
                if meta["has_stock"]:
                    shutil.copy2(char_dir / f"stock_{index}.png", costumes_dir / f"{meta['id']}_stc.png")

        entry = {
            "slug": self.BUILTIN_GIGA_SLUG,
            "name": self.BUILTIN_GIGA_NAME,
            "source": "builtin",
            "builtin": True,
            "date_added": datetime.now().isoformat(),
            "series_id": fighter_data.get("seriesID", 11),
            "costume_count": len(costume_meta),
            "has_css_icon": has_css_icon,
            "costume_meta": costume_meta,
        }

        self._commit_custom_character(entry)
        logger.info("Seeded built-in Giga Bowser custom character")
        return {"success": True, "seeded": True}

    def _commit_custom_character(self, entry: dict) -> None:
        """Insert or replace a custom-character entry in the vault metadata.

        Built-in fighters are now built on demand, i.e. while the app is live
        and other imports may be writing metadata.json — so go through the
        shared locked transaction rather than an unguarded read-modify-write
        (an unlocked write is what dropped the seeded Giga Bowser before).
        """
        def _upsert(metadata: dict) -> None:
            chars = metadata.setdefault("custom_characters", [])
            for index, char in enumerate(chars):
                if (char.get("slug") == entry["slug"]
                        or char.get("name", "").lower() == entry["name"].lower()):
                    chars[index] = entry
                    return
            chars.append(entry)

        if not self._uses_shared_vault():
            metadata = self._read_metadata()
            _upsert(metadata)
            self._write_metadata(metadata)
            return
        from core.metadata import metadata_transaction
        with metadata_transaction(default={"version": "1.0", "characters": {},
                                           "stages": {}, "custom_stages": [],
                                           "custom_characters": []}) as metadata:
            _upsert(metadata)

    def _uses_shared_vault(self) -> bool:
        """Whether this instance points at the app's live vault, and so should
        read/write metadata through the shared DAL (which may be SQLite-backed)
        rather than the plain JSON file. Tests point it elsewhere."""
        return self.storage_path == STORAGE_PATH

    def _vault_metadata(self) -> dict:
        """Vault metadata as the running app sees it."""
        if not self._uses_shared_vault():
            return self._read_metadata()
        from core.metadata import load_metadata
        data = load_metadata(default=None)
        return data if data is not None else self._read_metadata()

    def run_setup(
        self,
        iso_path: str,
        progress_callback: Optional[Callable[[str, int, str, int, int], None]] = None,
        on_temp_dir: Optional[Callable[[Path], None]] = None,
    ) -> dict:
        """
        Run the first-run setup process.

        Args:
            iso_path: Path to the user's vanilla Melee 1.02 ISO
            progress_callback: Callback(phase, percentage, message, completed, total)
            on_temp_dir: Callback(path) once the temporary project folder exists,
                so the caller can remove it if the process dies before the
                cleanup below runs (the setup job owns it).

        Returns:
            dict with 'success' bool and 'message' or 'error'
        """
        temp_dir = None

        try:
            # Phase 0: Copy bundled assets (production only)
            # Must happen before extraction since PRESERVE_CSP_CHARACTERS skips Sheik
            self._copy_bundled_sheik_assets()
            # Copy bundled sounds (more reliable than extracting from ISO)
            self._copy_bundled_sounds()

            # Create temp directory for MEX project
            temp_dir = Path(tempfile.mkdtemp(prefix='nucleus_setup_'))
            logger.info(f"Created temp directory: {temp_dir}")
            if on_temp_dir:
                on_temp_dir(temp_dir)

            # Phase 1: Extract ISO using mexcli create
            if progress_callback:
                progress_callback('extracting', 0, 'Extracting ISO (this may take 1-2 minutes)...', 0, 100)

            result = self._extract_iso(iso_path, temp_dir, progress_callback)
            if not result['success']:
                return result

            # Phase 2: Copy character assets
            if progress_callback:
                progress_callback('copying_characters', 0, 'Copying character assets...', 0, 100)

            result = self._copy_character_assets(temp_dir, progress_callback)
            if not result['success']:
                return result

            # Persist the complete flat reference bank used by generate_csp:
            # 28 fighter-data DATs plus all 124 vanilla costumes. These bytes
            # come from the user's verified ISO and live in writable storage;
            # they are never part of the installer.
            if progress_callback:
                progress_callback('copying_csp_references', 0,
                                  'Copying CSP reference data...', 0,
                                  self.CSP_REFERENCE_EXPECTED_FILE_COUNT)
            result = self._copy_csp_reference_dats(temp_dir, progress_callback)
            if not result['success']:
                return result

            # Phase 2b: STAGE built-in custom fighters from the extracted game.
            # Giga Bowser is present in Melee but normally inaccessible; we
            # package him into the same vault format as imported m-ex fighters —
            # but the renders that takes cost minutes, so setup only parks the
            # inputs here. The Custom Characters page shows him greyed out and
            # builds him on the first click.
            if progress_callback:
                progress_callback('seeding_builtins', 0,
                                  'Preparing built-in custom characters...', 0, 1)
            builtin_result = self.stage_builtin_giga_bowser(temp_dir)
            if not builtin_result.get('success'):
                logger.warning(f"Giga Bowser staging failed: {builtin_result.get('error')}")
            elif progress_callback:
                progress_callback('seeding_builtins', 100,
                                  'Prepared built-in custom characters', 1, 1)

            # Phase 3: Copy stage images
            if progress_callback:
                progress_callback('copying_stages', 0, 'Copying stage images...', 0, 6)

            result = self._copy_stage_images(temp_dir, progress_callback)
            if not result['success']:
                return result

            # (Phase 4, a copy of 27 vanilla costume DATs into the INSTALL's
            # processor/csp_data, is gone: nothing read those copies, and the
            # write broke the macOS signature and failed on the read-only
            # AppImage. generate_csp reads its vanilla DATs from the reference
            # bank copied above, in the data folder.)

            # Phase 4b: derive the Slippi bone-reference tables from the ISO.
            # These used to ship as 159 .bin files lifted out of retail Pl*.dat;
            # they are read straight off the disc instead (~1s, no extraction to
            # disk). Non-fatal: bone_refs.ensure_bone_refs re-derives lazily the
            # first time a costume is validated.
            if progress_callback:
                progress_callback('deriving_bone_refs', 0,
                                  'Deriving netplay-safety references...', 0, 1)
            try:
                from shared.vanilla_extract.bone_refs import ensure_bone_refs
                if ensure_bone_refs(iso_path) is None:
                    logger.warning("Bone reference derivation produced nothing")
                elif progress_callback:
                    progress_callback('deriving_bone_refs', 100,
                                      'Derived netplay-safety references', 1, 1)
            except Exception as e:
                logger.warning(f"Bone reference derivation failed: {e}")

            # Phase 4c: derive the vanilla reference art — the GmPause
            # textures, the IfAll slot manifests plus glyph previews, the
            # series emblems and the stage-select icons and banners. All four
            # used to ship as retail imagery in backend/assets. ~3s, and it
            # must run against the PROJECT (m-ex adds an IfAll root the raw
            # disc doesn't have — see menu_refs). Non-fatal: a set that fails
            # stays missing and is derived again when a project is opened.
            try:
                from shared.vanilla_extract.menu_refs import derive_menu_refs
                derive_menu_refs(temp_dir, progress_callback)
            except Exception as e:
                logger.warning(f"Menu reference derivation failed: {e}")

            # Phase 5: Extract menu sounds from main.ssm
            if progress_callback:
                progress_callback('extracting_sounds', 0, 'Extracting menu sounds...', 0, len(self.MENU_SOUNDS))

            result = self._extract_menu_sounds(temp_dir, progress_callback)
            if not result['success']:
                logger.warning(f"Sound extraction had issues: {result.get('error')}")
                # Don't fail setup, just warn - sounds are supplementary

            # Phase 5b: Seed each character's pristine voice/SFX bank into the
            # vault (storage/<Character>/sounds/original.ssm) from the temp
            # project, so sound packs can be created without opening a project
            # first (the vault sound engine, vault/importing/sound_banks.py).
            if progress_callback:
                progress_callback('seeding_sound_banks', 0,
                                  'Seeding character sound banks...', 0, 1)
            try:
                from vault.importing.sound_banks import seed_original_banks
                seeded = seed_original_banks(temp_dir)
                logger.info(f"Seeded {seeded} character sound banks into the vault")
                if progress_callback:
                    progress_callback('seeding_sound_banks', 100,
                                      f'Seeded {seeded} character sound banks', 1, 1)
            except Exception as e:
                # Non-fatal: packs fall back to seeding from an open project
                logger.warning(f"Sound bank seeding failed: {e}")

            # Phase 5c: derive the nucleOME UI sprites (Randall's cloud faces,
            # Fox/Falco shine frames) straight from the vanilla ISO. Non-fatal:
            # the /api/nucleome/sprites route re-derives lazily if this fails.
            if progress_callback:
                progress_callback('deriving_sprites', 0,
                                  'Deriving replay-browser sprites...', 0, 1)
            try:
                from shared.vanilla_extract import vanilla_refs
                from tracker.video import sprites
                vanilla_refs.record_vanilla_iso(iso_path)
                if sprites.ensure_sprites() is not None:
                    logger.info("Derived nucleOME sprite set")
                if progress_callback:
                    progress_callback('deriving_sprites', 100,
                                      'Derived replay-browser sprites', 1, 1)
            except Exception as e:
                logger.warning(f"nucleOME sprite derivation failed: {e}")

            # Phase 5d: fetch Watch Lite's character animation geometry
            # (slippilab's zips) if this build didn't bundle it — dev
            # checkouts keep them git-untracked, and an installer built
            # without them staged ships none. Non-fatal: Watch Lite falls
            # back to dot mode until the zips exist (a Settings re-run of
            # setup retries the download).
            try:
                from tracker.video import anim_fetch

                def _anim_progress(done, total, name):
                    if progress_callback:
                        progress_callback(
                            'downloading_anims',
                            int(100 * done / max(1, total)),
                            f'Downloading replay-viewer characters ({name})...',
                            done, total)

                anim_result = anim_fetch.ensure_anim_zips(progress_cb=_anim_progress)
                if anim_result.get('failed'):
                    logger.warning(
                        "Watch Lite animation download incomplete: %s", anim_result)
                elif anim_result.get('downloaded'):
                    logger.info(
                        "Downloaded %d Watch Lite animation zips",
                        anim_result['downloaded'])
            except Exception as e:
                logger.warning(f"Watch Lite animation download failed: {e}")

            # Warm the HD CSP cache from the freshly-extracted vanilla costumes,
            # so the first texture-pack/bundle export doesn't have to render the
            # vanilla slots. Background + idempotent; failures are non-fatal (the
            # export renders any missing HD CSP on demand). Patch-derived projects
            # are custom art and won't hit this, but mixed/vault projects do.
            if os.environ.get('NUCLEUS_HD_CSP_PRESEED', '1') != '0':
                try:
                    from shared.rendering.hd_csp_cache import preseed_vanilla_hd_csps
                    threading.Thread(
                        target=preseed_vanilla_hd_csps,
                        name='hd-csp-preseed',
                        daemon=True,
                    ).start()
                    logger.info("Started background HD CSP cache pre-seed")
                except Exception as e:
                    logger.warning(f"Could not start HD CSP pre-seed: {e}")

            # Success
            if progress_callback:
                progress_callback('complete', 100, 'Setup complete!', 100, 100)

            return {
                'success': True,
                'message': 'Vanilla assets extracted successfully',
                'characters': self.VANILLA_FIGHTER_COUNT,
                'builtin_custom_characters_staged': 1 if builtin_result.get('staged') else 0,
                'stages': len(self.STAGE_ICONS)
            }

        except Exception as e:
            logger.error(f"Setup failed: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }
        finally:
            # Cleanup temp directory
            if temp_dir and temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                    logger.info(f"Cleaned up temp directory: {temp_dir}")
                except Exception as e:
                    logger.warning(f"Failed to cleanup temp directory: {e}")

    def _get_folder_size(self, folder: Path) -> int:
        """Calculate total size of all files in a folder."""
        total = 0
        try:
            for f in folder.rglob('*'):
                if f.is_file():
                    total += f.stat().st_size
        except Exception:
            pass
        return total

    def _extract_iso(
        self,
        iso_path: str,
        temp_dir: Path,
        progress_callback: Optional[Callable] = None
    ) -> dict:
        """Extract ISO using mexcli create command."""
        try:
            # Run mexcli create
            cmd = [
                str(self.mexcli_path),
                'create',
                iso_path,
                str(temp_dir),
                'temp_project'
            ]

            logger.info(f"Running: {' '.join(cmd)}")

            # Owned (core/child_procs.py), so a crash cannot leave MexCLI still
            # writing into the temporary project the next start removes.
            process = own(subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=child_environment(),
            ))

            # Monitor folder size in background thread for progress
            stop_monitoring = threading.Event()
            current_phase = {'value': 'extracting', 'base_pct': 0}

            def monitor_size():
                phase_ticks = {'installing': 0, 'saving': 0}
                while not stop_monitoring.is_set():
                    size = self._get_folder_size(temp_dir)
                    size_mb = size // (1024 * 1024)

                    phase = current_phase['value']

                    if phase == 'extracting':
                        # Extraction: 0-70% based on folder size
                        pct = min(70, int((size / self.EXPECTED_EXTRACTION_SIZE) * 70))
                    elif phase == 'installing':
                        # Installing: 70-85%, increment over time
                        phase_ticks['installing'] += 1
                        pct = min(85, 70 + phase_ticks['installing'])
                    elif phase == 'saving':
                        # Saving: 85-95%, increment over time
                        phase_ticks['saving'] += 1
                        pct = min(95, 85 + phase_ticks['saving'])
                    else:
                        pct = 100

                    if progress_callback and phase != 'complete':
                        msg = {
                            'extracting': f'Extracting ISO files... ({size_mb} MB)',
                            'installing': f'Installing MEX framework... ({size_mb} MB)',
                            'saving': 'Finalizing project...'
                        }.get(phase, 'Processing...')
                        progress_callback('extracting', pct, msg, pct, 100)

                    time.sleep(0.3)

            monitor_thread = threading.Thread(target=monitor_size, daemon=True)
            monitor_thread.start()

            # Collect all output for logging
            stdout_lines = []

            # Read output line by line for phase changes
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue

                # Save all output for error logging
                stdout_lines.append(line)
                logger.info(f"mexcli output: {line}")

                try:
                    data = json.loads(line)
                    status = data.get('status', '')

                    if status == 'installing':
                        current_phase['value'] = 'installing'
                        current_phase['base_pct'] = 70
                    elif status == 'saving':
                        current_phase['value'] = 'saving'
                        current_phase['base_pct'] = 85
                    elif status == 'complete':
                        current_phase['value'] = 'complete'
                        if progress_callback:
                            progress_callback('extracting', 100, 'Extraction complete', 100, 100)

                except json.JSONDecodeError:
                    # Not JSON, just regular output
                    pass

            process.wait()
            stop_monitoring.set()
            monitor_thread.join(timeout=1)

            if process.returncode != 0:
                stderr = process.stderr.read()
                stdout_text = '\n'.join(stdout_lines)
                logger.error(f"mexcli failed with return code {process.returncode}")
                logger.error(f"mexcli stdout: {stdout_text}")
                logger.error(f"mexcli stderr: {stderr}")
                return {
                    'success': False,
                    'error': f'mexcli create failed (code {process.returncode}): {stdout_text or stderr}'
                }

            # Verify extraction produced expected files
            data_dir = temp_dir / 'data' / 'fighters'
            if not data_dir.exists():
                return {
                    'success': False,
                    'error': 'Extraction did not produce expected fighter data'
                }

            return {'success': True}

        except Exception as e:
            return {
                'success': False,
                'error': f'Failed to extract ISO: {e}'
            }

    def _copy_character_assets(
        self,
        temp_dir: Path,
        progress_callback: Optional[Callable] = None
    ) -> dict:
        """Copy character assets from extracted temp project to vanilla dir."""
        try:
            # Ensure vanilla directory exists
            self.vanilla_dir.mkdir(parents=True, exist_ok=True)

            # Read fighter JSONs
            data_dir = temp_dir / 'data' / 'fighters'
            assets_dir = temp_dir / 'assets'
            files_dir = temp_dir / 'files'

            total_costumes = 0
            completed_costumes = 0

            # First pass: count total costumes
            for i in range(self.VANILLA_FIGHTER_COUNT):
                json_path = data_dir / f'{i:03d}.json'
                if json_path.exists():
                    with open(json_path, 'r') as f:
                        fighter_data = json.load(f)
                    total_costumes += len(fighter_data.get('costumes', []))

            # Second pass: copy assets
            for i in range(self.VANILLA_FIGHTER_COUNT):
                json_path = data_dir / f'{i:03d}.json'
                if not json_path.exists():
                    logger.warning(f"Fighter JSON not found: {json_path}")
                    continue

                with open(json_path, 'r') as f:
                    fighter_data = json.load(f)

                char_name = fighter_data.get('name', f'Unknown_{i}')
                char_dir = self.vanilla_dir / char_name
                char_dir.mkdir(parents=True, exist_ok=True)

                # Copy CSS icon (character select screen icon)
                css_icon_ref = fighter_data.get('assets', {}).get('cssIcon', '')
                if css_icon_ref:
                    # Convert "css\\icon" to "css/icon.png"
                    css_icon_path = assets_dir / (css_icon_ref.replace('\\', '/') + '.png')
                    if css_icon_path.exists():
                        shutil.copy2(css_icon_path, char_dir / 'css_icon.png')

                # Copy animation archive (PlXxAJ.dat)
                anim_file = fighter_data.get('files', {}).get('animFile', '')
                if anim_file:
                    anim_path = files_dir / anim_file
                    if anim_path.exists():
                        shutil.copy2(anim_path, char_dir / anim_file)

                # Copy costumes
                for costume in fighter_data.get('costumes', []):
                    costume_file = costume.get('file', {}).get('fileName', '')
                    if not costume_file:
                        continue

                    # Create costume folder (e.g., PlMrNr)
                    dat_path, canonical_name = self._resolve_csp_reference_source(files_dir, costume_file)
                    if dat_path is None:
                        raise FileNotFoundError(f'Vanilla costume archive missing: {costume_file}')
                    costume_code = Path(canonical_name).stem
                    costume_dir = char_dir / costume_code
                    costume_dir.mkdir(parents=True, exist_ok=True)

                    # Copy DAT file
                    shutil.copy2(dat_path, costume_dir / canonical_name)

                    # Check for asset overrides (e.g., Mr. Game & Watch has wrong mappings)
                    char_overrides = self.ASSET_OVERRIDES.get(char_name, {})
                    costume_overrides = char_overrides.get(costume_code, {})

                    # Copy CSP (skip for characters with preserved CSPs in git)
                    if char_name not in self.PRESERVE_CSP_CHARACTERS:
                        csp_ref = costume_overrides.get('csp') or costume.get('csp', '')
                        if csp_ref:
                            csp_path = assets_dir / (csp_ref.replace('\\', '/') + '.png')
                            if csp_path.exists():
                                shutil.copy2(csp_path, costume_dir / 'csp.png')

                    # Copy stock icon
                    icon_ref = costume_overrides.get('icon') or costume.get('icon', '')
                    if icon_ref:
                        icon_path = assets_dir / (icon_ref.replace('\\', '/') + '.png')
                        if icon_path.exists():
                            shutil.copy2(icon_path, costume_dir / 'stock.png')

                    completed_costumes += 1

                    if progress_callback:
                        pct = int((completed_costumes / total_costumes) * 100)
                        progress_callback(
                            'copying_characters',
                            pct,
                            f'Copying {char_name} - {costume.get("name", costume_code)}',
                            completed_costumes,
                            total_costumes
                        )

            return {'success': True}

        except Exception as e:
            logger.error(f"Failed to copy character assets: {e}", exc_info=True)
            return {
                'success': False,
                'error': f'Failed to copy character assets: {e}'
            }

    def _copy_stage_images(
        self,
        temp_dir: Path,
        progress_callback: Optional[Callable] = None
    ) -> dict:
        """Copy stage images from extracted temp project."""
        try:
            # Ensure stages directory exists
            self.stages_dir.mkdir(parents=True, exist_ok=True)

            sss_dir = temp_dir / 'assets' / 'sss'

            completed = 0
            for src_name, dst_name in self.STAGE_ICONS.items():
                src_path = sss_dir / src_name
                dst_path = self.stages_dir / dst_name

                if src_path.exists():
                    shutil.copy2(src_path, dst_path)
                    logger.info(f"Copied stage: {src_name} -> {dst_name}")
                else:
                    logger.warning(f"Stage icon not found: {src_path}")

                completed += 1

                if progress_callback:
                    pct = int((completed / len(self.STAGE_ICONS)) * 100)
                    progress_callback(
                        'copying_stages',
                        pct,
                        f'Copying {dst_name}',
                        completed,
                        len(self.STAGE_ICONS)
                    )

            return {'success': True}

        except Exception as e:
            logger.error(f"Failed to copy stage images: {e}", exc_info=True)
            return {
                'success': False,
                'error': f'Failed to copy stage images: {e}'
            }

    @staticmethod
    def _resolve_csp_reference_source(files_dir: Path, listed_name: str):
        """Resolve a fighter JSON filename to (source, canonical DAT name).

        Vanilla Red Falcon is region-resolved in fighter JSON as ``PlCaRe.``;
        depending on the extracted project it may be ``.dat`` or ``.usd``.
        The renderer's reference bank uses the canonical ``.dat`` name for both.
        """
        raw_name = Path(str(listed_name)).name
        if not raw_name:
            return None, None

        if raw_name.endswith('.'):
            base = raw_name[:-1]
            candidates = [f"{base}.dat", f"{base}.usd"]
            canonical = f"{base}.dat"
        else:
            suffix = Path(raw_name).suffix.lower()
            if suffix not in ('.dat', '.usd'):
                return None, None
            base = str(Path(raw_name).with_suffix(''))
            canonical = f"{base}.dat"
            other = '.usd' if suffix == '.dat' else '.dat'
            candidates = [raw_name, f"{base}{other}"]

        for candidate in candidates:
            source = files_dir / candidate
            if source.is_file():
                return source, canonical
        return None, canonical

    def _copy_csp_reference_dats(
        self,
        temp_dir: Path,
        progress_callback: Optional[Callable] = None,
    ) -> dict:
        """Persist all CSP reference DATs extracted from the user's ISO.

        The standalone CSP Maker's generated ``data/vanilla_fighters`` folder
        contains this same bank, but that developer build output must never ship
        in Nucleus. Build the bank from the temporary mexcli project instead and
        atomically publish each file into writable ``storage/test-base/files``.
        """
        data_dir = temp_dir / 'data' / 'fighters'
        files_dir = temp_dir / 'files'
        required_indices = tuple(range(self.VANILLA_FIGHTER_COUNT)) + tuple(
            self.CSP_REFERENCE_EXTRA_FIGHTER_INDICES
        )
        references = {}
        missing = []

        try:
            for fighter_index in required_indices:
                json_path = data_dir / f'{fighter_index:03d}.json'
                if not json_path.is_file():
                    missing.append(json_path.name)
                    continue
                fighter = json.loads(json_path.read_text(encoding='utf-8'))
                listed_names = []
                fighter_data_path = fighter.get('files', {}).get('fighterDataPath')
                if fighter_data_path:
                    listed_names.append(fighter_data_path)
                # The 124 retail costume models belong to indices 0-26. Giga's
                # PlGkNr is synthesized by the MEX project; only his retail
                # PlGk.dat ftData belongs in the vanilla reference bank.
                if fighter_index < self.VANILLA_FIGHTER_COUNT:
                    listed_names.extend(
                        costume.get('file', {}).get('fileName')
                        for costume in fighter.get('costumes', [])
                        if costume.get('file', {}).get('fileName')
                    )

                for listed_name in listed_names:
                    source, canonical = self._resolve_csp_reference_source(
                        files_dir, listed_name
                    )
                    if source is None:
                        missing.append(str(listed_name))
                    else:
                        references[canonical] = source

            if missing:
                preview = ', '.join(missing[:5])
                return {
                    'success': False,
                    'error': (f'ISO extraction is missing {len(missing)} CSP reference '
                              f'file(s): {preview}'),
                }
            if len(references) != self.CSP_REFERENCE_EXPECTED_FILE_COUNT:
                return {
                    'success': False,
                    'error': (f'ISO extraction produced {len(references)} unique CSP '
                              f'references; expected {self.CSP_REFERENCE_EXPECTED_FILE_COUNT}'),
                }

            self.csp_reference_dir.mkdir(parents=True, exist_ok=True)
            total = len(references)
            for completed, (name, source) in enumerate(
                    sorted(references.items()), start=1):
                destination = self.csp_reference_dir / name
                temporary = destination.with_name(destination.name + '.setup.tmp')
                try:
                    shutil.copy2(source, temporary)
                    file_retry.replace(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)
                if progress_callback:
                    progress_callback(
                        'copying_csp_references',
                        int(completed * 100 / total),
                        f'Copying {name}',
                        completed,
                        total,
                    )

            manifest = {
                'version': self.CSP_REFERENCE_MANIFEST_VERSION,
                'source': 'user-verified-iso',
                'files': sorted(references),
            }
            self.csp_reference_manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest_tmp = self.csp_reference_manifest.with_suffix('.json.tmp')
            try:
                manifest_tmp.write_text(
                    json.dumps(manifest, indent=2) + '\n', encoding='utf-8'
                )
                file_retry.replace(manifest_tmp, self.csp_reference_manifest)
            finally:
                manifest_tmp.unlink(missing_ok=True)

            logger.info(
                "Copied %d user-derived CSP references to %s",
                total, self.csp_reference_dir,
            )
            return {'success': True, 'copied': total}
        except Exception as e:
            logger.error("Failed to copy CSP reference DATs: %s", e, exc_info=True)
            return {'success': False, 'error': f'Failed to copy CSP reference DATs: {e}'}

    def _extract_menu_sounds(
        self,
        temp_dir: Path,
        progress_callback: Optional[Callable] = None
    ) -> dict:
        """Extract menu sounds from main.ssm using HSDRawViewer."""
        try:
            # Find main.ssm in the extracted ISO
            main_ssm = temp_dir / 'files' / 'audio' / 'us' / 'main.ssm'
            if not main_ssm.exists():
                # Try alternate location
                main_ssm = temp_dir / 'files' / 'audio' / 'main.ssm'

            if not main_ssm.exists():
                logger.warning(f"main.ssm not found in extracted ISO")
                return {'success': False, 'error': 'main.ssm not found'}

            # Check if HSDRawViewer exists
            if not self.hsdraw_path.exists():
                # Windows development builds may have only the Debug renderer.
                if os.name == "nt":
                    debug_path = self.hsdraw_path.parent.parent.parent / "Debug" / "net6.0-windows" / "HSDRawViewer.exe"
                    if debug_path.exists():
                        self.hsdraw_path = debug_path
                if not self.hsdraw_path.exists():
                    logger.warning(f"CSP renderer not found at {self.hsdraw_path}")
                    return {'success': False, 'error': 'CSP renderer not found'}

            # Ensure sounds directory exists
            self.sounds_dir.mkdir(parents=True, exist_ok=True)

            # Create JSON mapping file for sound names
            names_json = self.sounds_dir / 'menu_sounds.json'
            with open(names_json, 'w') as f:
                json.dump({str(k): v for k, v in self.MENU_SOUNDS.items()}, f, indent=2)

            # Run HSDRawViewer to extract sounds
            cmd = [
                str(self.hsdraw_path),
                '--sound', 'extract',
                str(main_ssm),
                str(self.sounds_dir),
                '--names', str(names_json)
            ]

            logger.info(f"Running: {' '.join(cmd)}")

            if progress_callback:
                progress_callback('extracting_sounds', 10, 'Extracting sounds from main.ssm...', 1, len(self.MENU_SOUNDS))

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                **get_subprocess_args()
            )

            if result.returncode != 0:
                logger.error(f"HSDRawViewer failed: {result.stderr}")
                return {'success': False, 'error': f'Sound extraction failed: {result.stderr}'}

            # Remove numbered sound files, keep only named ones
            for f in self.sounds_dir.glob('sound_*.wav'):
                f.unlink()

            # Verify we got the sounds we wanted
            extracted_count = 0
            for name in self.MENU_SOUNDS.values():
                sound_file = self.sounds_dir / f'{name}.wav'
                if sound_file.exists():
                    extracted_count += 1

            if progress_callback:
                progress_callback('extracting_sounds', 100, f'Extracted {extracted_count} menu sounds', extracted_count, len(self.MENU_SOUNDS))

            logger.info(f"Extracted {extracted_count}/{len(self.MENU_SOUNDS)} menu sounds")
            return {'success': True, 'extracted': extracted_count}

        except subprocess.TimeoutExpired:
            logger.error("Sound extraction timed out")
            return {'success': False, 'error': 'Sound extraction timed out'}
        except Exception as e:
            logger.error(f"Failed to extract menu sounds: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}
