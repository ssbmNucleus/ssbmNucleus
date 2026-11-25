"""
MexManager: one open MexCLI project workspace (was mex_bridge.py).

This module provides a Python interface to MexManager's costume import and ISO export
functionality through the mexcli command-line interface.

It must not import ``core`` (that runs core.config): ``core.state`` imports this
module while ``core`` is still initialising, and standalone workers use it without
the app's configuration. One-shot commands at the configured MexCLI path are
``mexcli.commands``.
"""

import json
import subprocess
import os
from pathlib import Path
from typing import Dict, List, Optional, Callable
import logging
import threading
import time

# Configure logging
logger = logging.getLogger(__name__)

MEXCLI_EXPORT_TIMEOUT_SECONDS = 2 * 60 * 60
MEXCLI_EXPORT_STOP_GRACE_SECONDS = 5
MEXCLI_STDERR_LIMIT = 64 * 1024
MEXCLI_STDOUT_LEFTOVER_LINES = 200
# Called with the long-running export process. The app sets it to
# core.child_procs.own so a backend crash takes MexCLI with it; this module
# cannot import core itself (see above).
on_spawn = None


def _helper_environment():
    """What MexCLI is started with: the backend's environment without Nucleus's settings and secrets, because
    MexCLI reads imported files. The same rule as core/child_env.child_environment, written out here because
    this module cannot import core (test_helper_environment holds the two to the same answer)."""
    return {key: value for key, value in os.environ.items()
            if not key.upper().startswith(('NUCLEUS_', '_PYI', '_MEI'))
            and not key.upper().endswith(('_API_KEY', '_TOKEN', '_SECRET', '_SECRET_KEY', '_PASSWORD'))
            and key.upper() not in ('PYTHONPATH', 'PYTHONHOME')}


def _upgrade_nucleus_codes(project_path) -> None:
    """Move a project's Now Playing entry off an earlier version of the code
    (projects/nowplaying/upgrade.py) before MexCLI compiles files/codes.ini into
    the build. Every ISO export and `save` passes here. Best-effort: a failure is
    logged and the build goes on with the code it has."""
    try:
        from projects.nowplaying.upgrade import upgrade_project
    except ImportError as e:            # a standalone worker without the app's packages
        logger.debug(f"Now Playing upgrade unavailable: {e}")
        return
    try:
        upgrade_project(project_path)
    except Exception as e:              # noqa: BLE001 -- never stops an export
        logger.warning(f"Now Playing upgrade skipped for {project_path}: {e}")


def fighter_files(project) -> List[Path]:
    """A project's fighter JSONs in internal-id order, the way m-ex loads them:
    from the .mexproj's ``fighterSaveMap``. ``data/fighters`` can hold stale
    ``NNN.json`` past the end, because m-ex rewrites the list on Save but never
    deletes a file (a removed fighter leaves the old last one behind), so a glob
    of that folder sees fighters that are not there. ``project`` is the .mexproj
    or its folder; a project with no readable saved fighter list (a bare test
    layout) falls back to the folder's files in name order."""
    project = Path(project)
    folder = (project if project.is_dir() else project.parent) / "data" / "fighters"
    mexproj = project if project.suffix == ".mexproj" else next(iter(sorted(project.glob("*.mexproj"))), None)
    saved = None
    if mexproj is not None and mexproj.is_file():
        try:
            saved = (json.loads(mexproj.read_text(encoding="utf-8-sig")).get("fighterSaveMap") or {}).get("filePaths")
        except (OSError, ValueError, AttributeError):
            saved = None   # unreadable: m-ex could not open it either; read the folder
    if saved is None:
        return sorted(folder.glob("*.json"))
    return [folder / name for name in saved]


class MexManagerError(Exception):
    """Base exception for MexManager operations"""
    pass


class MexExportCancelled(MexManagerError):
    """An ISO export was stopped on request (the MexCLI process was killed)."""
    pass


def _extract_mexcli_json(stdout: str):
    """Best-effort parse of a MexCLI JSON result from possibly-noisy stdout.

    Setter commands print progress lines (e.g. "Trimmed Image X Y") before the
    final (pretty-printed) JSON object. Returns the parsed object or None.
    """
    stdout = stdout.strip()
    if not stdout:
        return None

    # 1) whole output is JSON
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        pass

    # 2) drop known progress lines, then parse the remaining (multi-line) JSON
    lines = stdout.split('\n')
    filtered = '\n'.join(l for l in lines if not l.strip().startswith('Trimmed Image'))
    try:
        return json.loads(filtered)
    except json.JSONDecodeError:
        pass

    # 3) fall back to the last single-line JSON value
    for line in reversed(lines):
        line = line.strip()
        if line.startswith('{') or line.startswith('['):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    return None


class MexManager:
    """
    Python interface to MexManager CLI for costume import and ISO export.

    Example usage:
        mex = MexManager(
            cli_path="utility/mex/win-x64/mexcli.exe",
            project_path="build/project.mexproj"
        )

        info = mex.open_project()
        fighters = mex.list_fighters()
        mex.import_costume("Fox", "storage/Fox/custom/PlFxNr_custom.zip")
        mex.export_iso("output/game.iso")
    """

    def __init__(self, cli_path: str, project_path: str):
        """
        Initialize MexManager.

        Args:
            cli_path: Path to mexcli.exe executable
            project_path: Path to .mexproj project file
        """
        self.cli_path = Path(cli_path).resolve()  # Convert to absolute path
        self.project_path = Path(project_path).resolve()  # Convert to absolute path

        if not self.cli_path.exists():
            raise MexManagerError(f"MexCLI executable not found: {self.cli_path}")

        if not self.project_path.exists():
            raise MexManagerError(f"MEX project not found: {self.project_path}")

    def _run_command(self, *args) -> Dict:
        """
        Run mexcli command and return parsed JSON output.

        Args:
            *args: Command arguments to pass to mexcli

        Returns:
            Parsed JSON output from mexcli

        Raises:
            MexManagerError: If command fails or returns invalid JSON
        """
        cmd = [str(self.cli_path)] + list(args)

        logger.info(f"Running MexCLI command: {' '.join(cmd)}")

        try:
            # Run command from project directory so MexCLI can find project files
            # (files/, data/, assets/ directories relative to .mexproj)
            # MexCLI will still find backend resources via AppDomain.CurrentDomain.BaseDirectory

            # Hide CMD window on Windows
            creation_flags = 0
            if os.name == 'nt':  # Windows
                creation_flags = subprocess.CREATE_NO_WINDOW

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                cwd=str(self.project_path.parent),
                env=_helper_environment(),
                creationflags=creation_flags
            )

            logger.debug(f"MexCLI stdout: {result.stdout}")
            logger.debug(f"MexCLI stderr: {result.stderr}")
            logger.debug(f"MexCLI return code: {result.returncode}")

            # Try to parse JSON from stdout
            # MexCLI may output progress messages before JSON, so we need to find the JSON
            if result.stdout.strip():
                # Try to parse the entire output as JSON first
                try:
                    output = json.loads(result.stdout)
                    logger.info(f"MexCLI response: {json.dumps(output, indent=2)}")

                    # Check for error in JSON response
                    if isinstance(output, dict) and not output.get('success', True):
                        error_msg = output.get('error', 'Unknown error')
                        logger.error(f"MexCLI returned error: {error_msg}")
                        raise MexManagerError(f"MexCLI error: {error_msg}")

                    return output
                except json.JSONDecodeError:
                    # If full output isn't JSON, try parsing line by line to find JSON
                    # (MexCLI may output progress messages like "Trimmed Image X Y")
                    logger.debug("Full output is not JSON, trying line-by-line parsing")
                    lines = result.stdout.strip().split('\n')

                    # Filter out known progress messages but keep original lines (not stripped)
                    filtered_lines = [
                        line for line in lines
                        if not line.strip().startswith('Trimmed Image')
                    ]

                    # Rejoin filtered lines and try parsing as complete JSON
                    if filtered_lines:
                        filtered_output = '\n'.join(filtered_lines)
                        try:
                            output = json.loads(filtered_output)
                            logger.info(f"MexCLI response (filtered): {json.dumps(output, indent=2)}")

                            # Check for error in JSON response
                            if isinstance(output, dict) and not output.get('success', True):
                                error_msg = output.get('error', 'Unknown error')
                                logger.error(f"MexCLI returned error: {error_msg}")
                                raise MexManagerError(f"MexCLI error: {error_msg}")

                            return output
                        except json.JSONDecodeError as e:
                            # Still couldn't parse - try line-by-line as fallback
                            logger.debug(f"Filtered output still not valid JSON: {e}")

                    # Final fallback: Try from last line backwards to find valid JSON
                    for line in reversed(lines):
                        line = line.strip()
                        if line.startswith('{') or line.startswith('['):
                            try:
                                output = json.loads(line)
                                logger.info(f"MexCLI response (single line): {json.dumps(output, indent=2)}")

                                # Check for error in JSON response
                                if isinstance(output, dict) and not output.get('success', True):
                                    error_msg = output.get('error', 'Unknown error')
                                    logger.error(f"MexCLI returned error: {error_msg}")
                                    raise MexManagerError(f"MexCLI error: {error_msg}")

                                return output
                            except json.JSONDecodeError:
                                continue

                    # No valid JSON found anywhere
                    logger.error(f"Failed to parse any JSON from MexCLI output: {result.stdout}")
                    raise MexManagerError(f"Invalid JSON response from mexcli. Output: {result.stdout[:500]}")

            # If no stdout, check stderr
            if result.stderr:
                logger.error(f"MexCLI stderr output: {result.stderr}")
                raise MexManagerError(f"MexCLI error: {result.stderr}")

            # Return code non-zero without output
            if result.returncode != 0:
                logger.error(f"MexCLI failed with return code {result.returncode}")
                raise MexManagerError(f"MexCLI command failed with code {result.returncode}")

            # Empty but successful
            return {"success": True}

        except subprocess.SubprocessError as e:
            logger.error(f"Failed to execute mexcli: {e}")
            raise MexManagerError(f"Failed to execute mexcli: {e}")

    def open_project(self) -> Dict:
        """
        Open and validate MEX project.

        Returns:
            Dict with project information:
                - success: bool
                - projectPath: str
                - projectName: str
                - version: str
                - fighterCount: int
                - stageCount: int
        """
        return self._run_command("open", str(self.project_path))

    def get_info(self) -> Dict:
        """
        Get detailed project information.

        Returns:
            Dict with detailed project info including build info and counts
        """
        return self._run_command("info", str(self.project_path))

    def list_fighters(self) -> List[Dict]:
        """
        List all fighters in the project.

        Returns:
            List of fighter dicts with:
                - internalId: int
                - externalId: int
                - name: str
                - costumeCount: int
                - isMexFighter: bool
        """
        result = self._run_command("list-fighters", str(self.project_path))
        return result.get('fighters', [])

    def get_fighter_by_name(self, name: str) -> Optional[Dict]:
        """
        Get fighter info by name (case-insensitive).

        Args:
            name: Fighter name (e.g., "Fox", "Mario")

        Returns:
            Fighter dict or None if not found
        """
        fighters = self.list_fighters()
        for fighter in fighters:
            if fighter['name'].lower() == name.lower():
                return fighter
        return None

    def import_costume(self, fighter_name: str, zip_path: str) -> Dict:
        """
        Import costume ZIP file for a character.

        Args:
            fighter_name: Name of fighter (e.g., "Fox")
            zip_path: Path to costume ZIP file

        Returns:
            Dict with import results:
                - success: bool
                - fighter: str
                - fighterInternalId: int
                - costumesImported: int
                - totalCostumes: int
                - importLog: str
        """
        zip_path = Path(zip_path)
        if not zip_path.exists():
            raise MexManagerError(f"ZIP file not found: {zip_path}")

        result = self._run_command(
            "import-costume",
            str(self.project_path),
            fighter_name,
            str(zip_path)
        )
        padded = self.pad_paired_slots([fighter_name])
        if padded and isinstance(result, dict):
            result['pairedSlotsPadded'] = padded
        return result

    def import_costumes(self, manifest: Dict[str, list]) -> Dict:
        """
        Batch-import costumes across one or more fighters in a SINGLE workspace
        Save. Importing N costumes via import_costume() pays N full project
        recompiles (MxDt/MnSlChr/codes.gct/...); this collapses that to ONE and
        decodes all CSP/icon PNGs in parallel, producing a build byte-identical
        to the N sequential imports but ~7x faster on a mixed batch.

        Args:
            manifest: {fighter_name_or_id: [zip_path, ...], ...}

        Returns:
            Dict with: success, totalImported, totalFailed, perFighter
        """
        import tempfile
        clean: Dict[str, list] = {}
        for fighter, zips in manifest.items():
            paths = []
            for z in zips:
                p = Path(z)
                if not p.exists():
                    raise MexManagerError(f"ZIP file not found: {z}")
                paths.append(str(p.resolve()))
            if paths:
                clean[str(fighter)] = paths
        if not clean:
            return {"success": True, "totalImported": 0, "totalFailed": 0, "perFighter": {}}

        fd, manifest_path = tempfile.mkstemp(suffix=".json", prefix="nucleus_costume_batch_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(clean, f)
            result = self._run_command(
                "import-costumes",
                str(self.project_path),
                manifest_path,
            )
        finally:
            try:
                os.unlink(manifest_path)
            except OSError:
                pass
        padded = self.pad_paired_slots(list(clean))
        if padded and isinstance(result, dict):
            result['pairedSlotsPadded'] = padded
        return result

    # Zelda and Sheik are one fighter in two forms and share costume slots:
    # slot N of Zelda transforms into slot N of Sheik. A project where Zelda
    # has a costume in a slot Sheik lacks hangs on match load (a Dark Magician
    # Zelda costume added as a sixth slot did exactly that). Every import that
    # grows one side pads the other with a copy of its vanilla default.
    PAIRED_SLOTS = {'Zelda': ('Sheik', 'PlSkNr.dat'), 'Sheik': ('Zelda', 'PlZdNr.dat')}

    def pad_paired_slots(self, fighters) -> list:
        """Give a paired form a costume in every slot its partner has. -> list of what was added."""
        import tempfile
        import zipfile
        touched = {str(f) for f in fighters}
        pairs = {name: self.PAIRED_SLOTS[name] for name in self.PAIRED_SLOTS if name in touched}
        if not pairs:
            return []
        added = []
        try:
            counts = {f['name']: f['costumeCount'] for f in self.list_fighters()}
        except MexManagerError:
            return []
        for name, (partner, vanilla_file) in pairs.items():
            missing = counts.get(name, 0) - counts.get(partner, 0)
            if missing <= 0:
                continue
            try:
                from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
                source = ensure_vanilla_ref(vanilla_file)
            except Exception:  # noqa: BLE001 - padding must never fail the import itself
                source = None
            if not source:
                logger.warning(f"{name} now has {missing} more costume(s) than {partner}, and the vanilla "
                               f"{vanilla_file} needed to pair them is unavailable")
                continue
            fd, pad_zip = tempfile.mkstemp(suffix=".zip", prefix="nucleus_paired_")
            os.close(fd)
            try:
                with zipfile.ZipFile(pad_zip, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.write(source, vanilla_file)
                for _ in range(missing):
                    self._run_command("import-costume", str(self.project_path), partner, pad_zip)
                    added.append({'fighter': partner, 'costume': vanilla_file, 'pairs_with': name})
                counts[partner] = counts.get(partner, 0) + missing
            finally:
                try:
                    os.unlink(pad_zip)
                except OSError:
                    pass
        return added

    def reset_vanilla_costumes(self, manifest: Dict) -> Dict:
        """Atomically replace the listed fighters' costumes with vanilla sets.

        The manifest is prepared by the backend from the user's extracted
        vanilla assets and includes paired fighters in the same one-save call.
        """
        import tempfile

        fighters = manifest.get("fighters") if isinstance(manifest, dict) else None
        if not fighters:
            raise MexManagerError("Vanilla reset manifest contains no fighters")

        fd, manifest_path = tempfile.mkstemp(
            suffix=".json", prefix="nucleus_vanilla_reset_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(manifest, f)
            return self._run_command(
                "reset-vanilla-costumes",
                str(self.project_path),
                manifest_path,
            )
        finally:
            try:
                os.unlink(manifest_path)
            except OSError:
                pass

    def remove_costume(self, fighter_name: str, costume_index: int) -> Dict:
        """
        Remove a costume from a fighter.

        Args:
            fighter_name: Name of fighter (e.g., "Fox")
            costume_index: Index of costume to remove (0-based)

        Returns:
            Dict with removal results:
                - success: bool
                - fighter: str
                - fighterInternalId: int
                - removedCostume: dict (index, name, fileName)
                - remainingCostumes: int
        """
        result = self._run_command(
            "remove-costume",
            str(self.project_path),
            fighter_name,
            str(costume_index)
        )
        return result

    def remove_costumes(self, manifest: Dict[str, list]) -> Dict:
        """
        Batch-remove costumes across one or more fighters in a SINGLE workspace Save
        (vs N recompiles for N remove_costume calls). The CLI removes each fighter's
        indices in descending order so earlier removals don't shift later ones, giving
        the same final costume set as N sequential removes (one generated file,
        IfAll.usd, can differ in HSD layout but is functionally identical).

        Args:
            manifest: {fighter_name_or_id: [costume_index, ...], ...}

        Returns:
            Dict with: success, totalRemoved, totalFailed, perFighter
        """
        import tempfile
        clean: Dict[str, list] = {}
        for fighter, indices in manifest.items():
            idxs = [int(i) for i in indices]
            if idxs:
                clean[str(fighter)] = idxs
        if not clean:
            return {"success": True, "totalRemoved": 0, "totalFailed": 0, "perFighter": {}}

        fd, manifest_path = tempfile.mkstemp(suffix=".json", prefix="nucleus_costume_rm_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(clean, f)
            result = self._run_command(
                "remove-costumes",
                str(self.project_path),
                manifest_path,
            )
        finally:
            try:
                os.unlink(manifest_path)
            except OSError:
                pass
        return result

    def reorder_costume(self, fighter_name: str, from_index: int, to_index: int) -> Dict:
        """
        Reorder costumes by swapping positions.

        Args:
            fighter_name: Name of fighter (e.g., "Fox")
            from_index: Source costume index (0-based)
            to_index: Destination costume index (0-based)

        Returns:
            Dict with reorder results:
                - success: bool
                - fighter: str
                - fighterInternalId: int
                - reordered: dict (fromIndex, toIndex)
                - costumes: list of updated costumes

        Note:
            - For Ice Climbers (Popo), paired Nana costumes are automatically reordered
            - For Kirby, Kirby hat costumes across all fighters are automatically reordered
        """
        return self._run_command(
            "reorder-costume",
            str(self.project_path),
            fighter_name,
            str(from_index),
            str(to_index)
        )

    def reorder_costumes(self, manifest: Dict[str, list]) -> Dict:
        """
        Batch-reorder costumes across one or more fighters in a SINGLE workspace Save.

        reorder_costume() only SWAPS two slots, so a drag had to be replayed as
        |to-from| adjacent swaps -- i.e. |to-from| full project recompiles (~3s each)
        for ONE drag. Here a move is a proper SPLICE, so one drag is one move and a
        whole queue of drags collapses into one Save.

        Args:
            manifest: {fighter_name_or_id: [[from_index, to_index], ...], ...}
                      Moves apply in order, each against the list as it stands after
                      the previous one (a replay of the user's drags).

        Returns:
            Dict with: success, totalMoved, totalFailed, perFighter
        """
        import tempfile
        clean: Dict[str, list] = {}
        for fighter, moves in manifest.items():
            pairs = [[int(m[0]), int(m[1])] for m in moves if len(m) >= 2]
            if pairs:
                clean[str(fighter)] = pairs
        if not clean:
            return {"success": True, "totalMoved": 0, "totalFailed": 0, "perFighter": {}}

        fd, manifest_path = tempfile.mkstemp(suffix=".json", prefix="nucleus_costume_order_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(clean, f)
            return self._run_command(
                "reorder-costumes",
                str(self.project_path),
                manifest_path,
            )
        finally:
            try:
                os.unlink(manifest_path)
            except OSError:
                pass

    def save_project(self) -> Dict:
        """
        Save project changes.

        Returns:
            Dict with success status
        """
        _upgrade_nucleus_codes(self.project_path)
        return self._run_command("save", str(self.project_path))

    def recompile_csps(self) -> Dict:
        """
        Recompile CSP textures from their source PNG files.

        This regenerates .tex files from the .png sources without resizing.
        Useful when PNG files have been modified externally (e.g., replaced
        with texture pack placeholders).

        Returns:
            Dict with recompile results:
                - success: bool
                - recompiledCount: int
                - errorCount: int
                - message: str
        """
        return self._run_command("recompile-csps", str(self.project_path))

    def export_iso(
        self,
        output_path: str,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        csp_compression: float = 1.0,
        use_color_smash: bool = False,
        skip_compression: bool = False,
        should_stop: Optional[Callable[[], bool]] = None
    ) -> Dict:
        """
        Export modified ISO. `should_stop()` is polled while MexCLI runs; when it
        turns true the export process is killed and MexExportCancelled is raised
        (the partial output file is the caller's to remove).

        Args:
            output_path: Path for output ISO file
            progress_callback: Optional callback function(percentage, message)
            csp_compression: CSP compression level (0.1-1.0, default 1.0)
            use_color_smash: Enable color smash to save memory (default False)
            skip_compression: Skip ApplyCompression entirely (for texture pack mode)

        Returns:
            Dict with export results
        """
        cmd = [str(self.cli_path), "export", str(self.project_path), str(output_path),
               str(csp_compression), str(use_color_smash).lower(), str(skip_compression).lower()]
        # MexCLI reads codes.ini and compiles codes.gct during the export.
        _upgrade_nucleus_codes(self.project_path)

        try:
            # Run process with streaming output for progress
            # Use project directory as working directory so MexCLI can find project files
            # Prevent console window from appearing on Windows
            creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(self.project_path.parent),
                env=_helper_environment(),
                bufsize=1,  # Line buffered
                creationflags=creation_flags
            )
            if on_spawn is not None:
                on_spawn(process)

            final_result = {'value': None}
            warnings = []   # MexCLI {"status": "warning"} lines (e.g. the CSS heap budget guard)
            stderr_chunks = []
            stderr_size = [0]
            reader_errors = []
            # A MexCLI result that is not on one line (a pretty-printed error JSON)
            # used to parse as nothing, so a failed export reported the [DEBUG]
            # chatter on stderr instead of its cause. Keep the unparsed tail and
            # re-read it as one document if the run ends without a result.
            leftovers = []

            def drain_stdout():
                if not process.stdout:
                    return
                try:
                    for line in process.stdout:
                        line = line.strip()
                        if not line:
                            continue

                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            if len(leftovers) < MEXCLI_STDOUT_LEFTOVER_LINES:
                                leftovers.append(line)
                            continue
                        if not isinstance(data, dict):
                            continue
                        status = data.get('status', '')

                        if status == 'progress' and progress_callback:
                            percentage = data.get('percentage', 0)
                            message = data.get('message', '')
                            try:
                                progress_callback(percentage, message)
                            except Exception:
                                logger.exception('MexCLI export progress callback failed')
                        elif status == 'warning':
                            msg = data.get('message', '')
                            if msg:
                                warnings.append(msg)
                                logger.warning(f"MexCLI export: {msg}")
                                if progress_callback:
                                    try:
                                        progress_callback(data.get('percentage', 9), msg)
                                    except Exception:
                                        logger.exception('MexCLI export progress callback failed')
                        elif status in ('completed', 'error') or data.get('success') is not None:
                            final_result['value'] = data
                except Exception as exc:
                    reader_errors.append(('stdout', exc))

            def drain_stderr():
                if not process.stderr:
                    return
                try:
                    while True:
                        chunk = process.stderr.read(4096)
                        if not chunk:
                            break
                        if stderr_size[0] >= MEXCLI_STDERR_LIMIT:
                            continue
                        kept = chunk[:MEXCLI_STDERR_LIMIT - stderr_size[0]]
                        stderr_chunks.append(kept)
                        stderr_size[0] += len(kept)
                except Exception as exc:
                    reader_errors.append(('stderr', exc))

            readers = [
                threading.Thread(target=drain_stdout, daemon=True),
                threading.Thread(target=drain_stderr, daemon=True),
            ]
            for reader in readers:
                reader.start()

            def stop_owned_process():
                process.terminate()
                try:
                    process.wait(timeout=MEXCLI_EXPORT_STOP_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=MEXCLI_EXPORT_STOP_GRACE_SECONDS)

            try:
                deadline = time.monotonic() + MEXCLI_EXPORT_TIMEOUT_SECONDS
                while True:
                    if reader_errors:
                        stop_owned_process()
                        break
                    if should_stop is not None and should_stop():
                        stop_owned_process()
                        raise MexExportCancelled("ISO export stopped on request")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        stop_owned_process()
                        raise MexManagerError(
                            f"ISO export timed out after {MEXCLI_EXPORT_TIMEOUT_SECONDS} seconds")
                    try:
                        process.wait(timeout=min(0.25, remaining))
                        break
                    except subprocess.TimeoutExpired:
                        continue
            finally:
                for reader in readers:
                    reader.join(timeout=MEXCLI_EXPORT_STOP_GRACE_SECONDS)

            unfinished = [reader.name for reader in readers if reader.is_alive()]
            if unfinished:
                raise MexManagerError(
                    f"ISO export output reader did not finish: {', '.join(unfinished)}")
            if reader_errors:
                stream, error = reader_errors[0]
                raise MexManagerError(f"ISO export {stream} reader failed: {error}")

            final_result = final_result['value']
            if final_result is None and leftovers:
                try:
                    recovered = json.loads('\n'.join(leftovers))
                except json.JSONDecodeError:
                    recovered = None
                if isinstance(recovered, dict):
                    final_result = recovered
            stderr = ''.join(stderr_chunks)

            # The useful message lives in MexCLI's final JSON line, not stderr
            # (stderr carries only [DEBUG] chatter during exports).
            json_error = None
            if isinstance(final_result, dict) and (
                    final_result.get('success') is False
                    or final_result.get('status') == 'error'):
                json_error = final_result.get('error') or 'unknown MexCLI error'

            if process.returncode != 0:
                raise MexManagerError(f"ISO export failed: {json_error or stderr}")

            # An error JSON with a 0 exit code is still a failure — returning it
            # as a normal result let the backend finish the export as done for a
            # build that died (bugreport-968a8ba8).
            if json_error:
                raise MexManagerError(f"ISO export failed: {json_error}")

            result = final_result or {"success": True, "outputPath": output_path}
            # merge streamed warnings with the ones MexCLI put in its final line
            merged = list(result.get('warnings') or [])
            merged += [w for w in warnings if w not in merged]
            result['warnings'] = merged
            return result

        except subprocess.SubprocessError as e:
            raise MexManagerError(f"Failed to export ISO: {e}")

    def _run_command_with_stdin(self, stdin_data: str, *args) -> Dict:
        """Run mexcli command with data piped to stdin."""
        cmd = [str(self.cli_path)] + list(args)
        logger.info(f"Running MexCLI command (with stdin): {' '.join(cmd)}")

        try:
            creation_flags = 0
            if os.name == 'nt':
                creation_flags = subprocess.CREATE_NO_WINDOW

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                input=stdin_data,
                check=False,
                cwd=str(self.project_path.parent),
                env=_helper_environment(),
                creationflags=creation_flags,
                timeout=120
            )

            if result.stdout.strip():
                # Setter commands run workspace.Save(), which prints progress lines
                # like "Trimmed Image X Y" before the final JSON result. Recover the
                # JSON the same way _run_command does, so real errors aren't swallowed.
                output = _extract_mexcli_json(result.stdout)
                if output is not None:
                    if isinstance(output, dict) and not output.get('success', True):
                        raise MexManagerError(f"MexCLI error: {output.get('error', 'Unknown error')}")
                    return output

            if result.stderr:
                raise MexManagerError(f"MexCLI error: {result.stderr}")
            if result.returncode != 0:
                raise MexManagerError(f"MexCLI command failed with code {result.returncode}")
            return {"success": True}

        except subprocess.SubprocessError as e:
            raise MexManagerError(f"Failed to execute mexcli: {e}")

    def get_sss_layout(self) -> Dict:
        """Get full SSS layout data from the MEX project."""
        return self._run_command("get-sss-layout", str(self.project_path))

    def set_sss_layout(self, layout_json: str) -> Dict:
        """Write SSS layout data to the MEX project via stdin."""
        return self._run_command_with_stdin(
            layout_json, "set-sss-layout", str(self.project_path)
        )

    def get_css_layout(self) -> Dict:
        """Get full CSS layout data from the MEX project."""
        return self._run_command("get-css-layout", str(self.project_path))

    def set_css_layout(self, layout_json: str) -> Dict:
        """Write CSS layout data to the MEX project via stdin."""
        return self._run_command_with_stdin(
            layout_json, "set-css-layout", str(self.project_path)
        )

    def get_build(self) -> Dict:
        """Get the GameCube disc-banner metadata (title/creator/description) and a
        raw RGBA preview of the 96x32 banner image.

        Returns:
            Dict: success, shortName, longName, shortMaker, longMaker, description,
                  bannerWidth, bannerHeight, bannerRgbaBase64
        """
        return self._run_command("get-build", str(self.project_path))

    def set_build(self, payload: Dict) -> Dict:
        """Set the disc-banner fields and (optionally) the banner image.

        Args:
            payload: any of shortName, longName, shortMaker, longMaker, description,
                     bannerPngBase64 (base64-encoded PNG, any size -> resized to 96x32)
        """
        return self._run_command_with_stdin(
            json.dumps(payload), "set-build", str(self.project_path)
        )

    def get_character_id(self, character_name: str) -> Optional[int]:
        """
        Convert character name to internal ID.

        Args:
            character_name: Character name (e.g., "Fox")

        Returns:
            Internal ID or None if not found
        """
        fighter = self.get_fighter_by_name(character_name)
        return fighter['internalId'] if fighter else None


# Character name mapping for convenience
DEFAULT_CHARACTERS = {
    "Mario": "PlMrNr",
    "Fox": "PlFxNr",
    "C. Falcon": "PlCaNr",
    "DK": "PlDkNr",
    "Kirby": "PlKbNr",
    "Bowser": "PlKpNr",
    "Link": "PlLkNr",
    "Sheik": "PlSkNr",
    "Ness": "PlNsNr",
    "Peach": "PlPeNr",
    "Popo": "PlPpNr",
    "Nana": "PlNnNr",
    "Pikachu": "PlPkNr",
    "Samus": "PlSmNr",
    "Yoshi": "PlYsNr",
    "Jigglypuff": "PlPrNr",
    "Mewtwo": "PlMtNr",
    "Luigi": "PlLgNr",
    "Marth": "PlMsNr",
    "Zelda": "PlZdNr",
    "Young Link": "PlClNr",
    "Dr. Mario": "PlDrNr",
    "Falco": "PlFcNr",
    "Pichu": "PlPcNr",
    "Mr. Game & Watch": "PlGwNr",
    "Ganondorf": "PlGnNr",
    "Roy": "PlFeNr"
}


if __name__ == "__main__":
    # Example usage
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python app/backend/mexcli/project.py info")
        print("  python app/backend/mexcli/project.py list")
        print("  python app/backend/mexcli/project.py import <fighter> <zip>")
        sys.exit(1)

    # Initialize with default paths
    mex = MexManager(
        cli_path="utility/mex/win-x64/mexcli.exe",
        project_path="build/project.mexproj"
    )

    command = sys.argv[1].lower()

    if command == "info":
        info = mex.get_info()
        print(json.dumps(info, indent=2))

    elif command == "list":
        fighters = mex.list_fighters()
        for f in fighters:
            print(f"{f['name']:20} (ID: {f['internalId']:2}, Costumes: {f['costumeCount']:2})")

    elif command == "import" and len(sys.argv) >= 4:
        fighter = sys.argv[2]
        zip_path = sys.argv[3]
        result = mex.import_costume(fighter, zip_path)
        print(json.dumps(result, indent=2))

    else:
        print("Unknown command or missing arguments")
        sys.exit(1)
