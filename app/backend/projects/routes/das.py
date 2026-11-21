"""
DAS endpoints, project side: Dynamic Alternate Stages in the open project.

Handles DAS framework installation, the variants installed in the project, and
import/removal of stage variants from storage to project. These routes register
on `das_bp` from vault/routes/das.py (the vault's variant list and ISO scan), so
URLs and endpoint names are unchanged; naming, archive and migration helpers are
projects/install/das.py.
"""

import shutil
import zipfile
import logging
from pathlib import Path
from flask import request, jsonify

import file_retry
from core.config import PROJECT_ROOT, STORAGE_PATH, BASE_PATH
from core.metadata import load_metadata
from core.state import get_project_files_dir, mexcli_lock
from projects.install.das_loaders import has_das_loader, install_das_loader
from projects.install.das import (
    DAS_DEFAULT_SCREENSHOTS, DAS_STAGES, add_button_indicator, direct_variant_child,
    extract_button_indicator, find_stage_screenshot, get_variant_match_key,
    migrate_das_folder_extensions, migrate_stadium_variant_stems, normalize_variant_name,
    sanitize_filename, select_stage_archive_member, stadium_runtime_variant_name,
    stadium_transformation_members, stadium_variant_hashed_match_key,
    stadium_variant_match_key, strip_button_indicator,
)
from vault.routes.das import das_bp

logger = logging.getLogger(__name__)


@das_bp.route('/api/mex/das/status', methods=['GET'])
def das_get_status():
    """Whether the DAS framework is set up in the open project.

    `installedStages` lists the stages whose root file is really the DAS
    loader with a variants folder beside it; a stage folder alone does not
    work in game. `installed` is true once DAS was set up at all (a loader or
    a stage folder), and `missingStages` then lists the stages still without a
    loader (an install that found no vanilla source for them), so the Stages
    tab can offer the install again.
    """
    try:
        project_files_path = get_project_files_dir()
        das_source = BASE_PATH / "utility" / "DynamicAlternateStages"
        installed_stages = []
        set_up = False

        for stage_code in DAS_STAGES:
            if not (project_files_path / stage_code).is_dir():
                continue
            set_up = True
            if has_das_loader(stage_code, project_files_path, loader_dir=das_source):
                installed_stages.append(stage_code)

        return jsonify({
            'success': True,
            'installed': set_up,
            'installedStages': installed_stages,
            'missingStages': ([code for code in DAS_STAGES if code not in installed_stages]
                              if set_up else []),
            'totalStages': len(DAS_STAGES)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@das_bp.route('/api/mex/das/install', methods=['POST'])
def das_install():
    """Install DAS framework"""
    try:
        logger.info("=== DAS FRAMEWORK INSTALLATION ===")

        # Use BASE_PATH for bundled resources (includes DAS files)
        das_source = BASE_PATH / "utility" / "DynamicAlternateStages"
        project_files = get_project_files_dir()

        if not das_source.exists():
            return jsonify({
                'success': False,
                'error': f'DAS framework source not found at {das_source}'
            }), 500

        project_files.mkdir(parents=True, exist_ok=True)

        # Install each stage
        missing_loaders = []
        for stage_code, stage_info in DAS_STAGES.items():
            logger.info(f"Installing DAS for {stage_info['name']} ({stage_code})...")

            # Root-level file uses .usd for Pokemon Stadium, .dat for others
            root_ext = '.usd' if stage_code == 'GrPs' else '.dat'

            # Create stage folder first
            stage_folder = project_files / stage_code
            stage_folder.mkdir(exist_ok=True)
            logger.info(f"  Created folder: {stage_code}/")

            # Get paths — alts inside the folder are always .dat
            original_stage = project_files / f"{stage_code}{root_ext}"
            loader_src = das_source / f"{stage_code}{root_ext}"
            vanilla_in_folder = stage_folder / "vanilla.dat"

            # If vanilla variant doesn't exist yet and original stage exists, copy it into folder
            if not vanilla_in_folder.exists() and original_stage.exists():
                shutil.copy2(original_stage, vanilla_in_folder)
                logger.info(f"  Copied vanilla stage to {stage_code}/vanilla.dat")

                # Copy default screenshot for vanilla variant to storage
                if stage_code in DAS_DEFAULT_SCREENSHOTS:
                    # Stage icons are extracted to PROJECT_ROOT at setup
                    # (first_run_setup._copy_stage_images). The BASE_PATH branch
                    # is a dead fallback kept only as a guard: NO platform bundles
                    # utility/assets/stages any more -- Windows never did, and the
                    # Linux/mac stage entries were dropped once it was confirmed
                    # the icons always come from the user's own ISO. A missing
                    # screenshot is cosmetic; DAS install proceeds either way.
                    default_screenshot = PROJECT_ROOT / "utility" / "assets" / "stages" / DAS_DEFAULT_SCREENSHOTS[stage_code]
                    if not default_screenshot.exists():
                        default_screenshot = BASE_PATH / "utility" / "assets" / "stages" / DAS_DEFAULT_SCREENSHOTS[stage_code]
                    if default_screenshot.exists():
                        storage_das_folder = STORAGE_PATH / 'das' / stage_info['folder']
                        storage_das_folder.mkdir(parents=True, exist_ok=True)
                        storage_screenshot = storage_das_folder / f"vanilla_screenshot.png"
                        shutil.copy2(default_screenshot, storage_screenshot)
                        logger.info(f"  Copied default screenshot to storage: {storage_screenshot.name}")

            # Install DAS loader (replaces original stage file), rebuilt from a
            # shipped patch against the user's own vanilla root
            # (projects/install/das_loaders.py).
            if install_das_loader(stage_code, project_files, loader_dir=das_source):
                logger.info(f"  Installed DAS loader: {stage_code}{root_ext}")
            else:
                missing_loaders.append(stage_info['name'])
                logger.warning(f"  DAS loader unavailable: {loader_src}")

        # Heal any legacy .usd alts left by older versions so a re-install
        # repairs an existing project, not just fresh ones.
        migrate_das_folder_extensions(project_files)

        logger.info("DAS framework installed successfully")

        response = {
            'success': True,
            'message': 'DAS framework installed successfully'
        }
        if missing_loaders:
            response['warning'] = (
                f"No alternate-stage loader for {', '.join(missing_loaders)}: it is "
                "made from the stage file in your own Melee 1.02 ISO. Set your vanilla "
                "ISO in Settings and install again.")
        return jsonify(response)
    except Exception as e:
        logger.error(f"DAS installation error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@das_bp.route('/api/mex/das/stages', methods=['GET'])
def das_list_stages():
    """List all DAS-supported stages"""
    try:
        stages = []
        for stage_code, stage_info in DAS_STAGES.items():
            stages.append({
                'code': stage_code,
                'name': stage_info['name'],
                'folder': stage_info['folder']
            })

        return jsonify({
            'success': True,
            'stages': stages
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@das_bp.route('/api/mex/das/restore-vanilla', methods=['POST'])
def das_restore_vanilla():
    """Add the pristine vanilla stage back to one installed DAS folder."""
    data = request.get_json(silent=True) or {}
    stage_code = data.get('stageCode')
    if stage_code not in DAS_STAGES:
        return jsonify({
            'success': False,
            'error': f'Unknown stage code: {stage_code}',
        }), 400

    try:
        project_files = get_project_files_dir()
        stage_folder = project_files / stage_code
        loader_ext = '.usd' if stage_code == 'GrPs' else '.dat'
        loader_path = project_files / f'{stage_code}{loader_ext}'
        if not stage_folder.is_dir() or not loader_path.exists():
            return jsonify({
                'success': False,
                'error': 'DAS is not installed for this stage',
            }), 409

        destination = stage_folder / 'vanilla.dat'
        with mexcli_lock:
            if destination.exists():
                return jsonify({
                    'success': True,
                    'alreadyPresent': True,
                    'message': 'Vanilla stage is already installed',
                })

            from shared.vanilla_extract.vanilla_refs import ensure_vanilla_ref
            source_name = f'{stage_code}{loader_ext}'
            source = ensure_vanilla_ref(source_name)
            if not source or not Path(source).is_file():
                return jsonify({
                    'success': False,
                    'error': (
                        f'Vanilla reference {source_name} is unavailable. '
                        'Refresh vanilla assets in Settings and try again.'
                    ),
                }), 404

            # Copy to a sibling temp and replace so the loader can never observe
            # a partial stage file.
            temp_path = stage_folder / '.vanilla.restore.tmp'
            try:
                shutil.copy2(source, temp_path)
                file_retry.replace(temp_path, destination)
            finally:
                temp_path.unlink(missing_ok=True)

        logger.info('Restored vanilla DAS stage: %s', destination)
        return jsonify({
            'success': True,
            'alreadyPresent': False,
            'message': f"Vanilla {DAS_STAGES[stage_code]['name']} restored",
        })
    except Exception as e:
        logger.error('DAS vanilla restore failed: %s', e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@das_bp.route('/api/mex/das/stages/<stage_code>/variants', methods=['GET'])
def das_get_stage_variants(stage_code):
    """Get DAS variants for a specific stage from MEX project"""
    try:
        if stage_code not in DAS_STAGES:
            return jsonify({
                'success': False,
                'error': f'Unknown stage code: {stage_code}'
            }), 400

        project_files = get_project_files_dir()
        # Heal any legacy .usd alts before enumerating: older versions wrote
        # Stadium variants as .usd, which the m-ex loader rejects (and which the
        # .dat-only glob below would hide). This normalizes them to .dat so they
        # appear in the panel and the next build won't crash.
        migrate_das_folder_extensions(project_files, [stage_code])
        if stage_code == 'GrPs':
            migrate_stadium_variant_stems(project_files)
        stage_folder = project_files / stage_code
        variants = []

        if stage_folder.exists() and stage_folder.is_dir():
            file_pattern = '*.dat'

            # Load metadata to get slippi status and other info
            metadata = load_metadata(default={})

            stage_folder_name = DAS_STAGES[stage_code]['folder']
            stage_metadata = metadata.get('stages', {}).get(stage_folder_name, {})
            metadata_variants = {v['id']: v for v in stage_metadata.get('variants', [])}

            for stage_file in stage_folder.glob(file_pattern):
                filename_stem = stage_file.stem  # e.g., "AutumnDreamland" or "AutumnDreamland(B)"

                # Extract button indicator (e.g., "AutumnDreamland(B)" -> "B")
                button = extract_button_indicator(filename_stem)

                # Strip button indicator for matching
                display_name_from_file = strip_button_indicator(filename_stem)

                # Reverse-lookup: display name -> variant_id using metadata
                variant_id_for_screenshot = None
                variant_meta = {}

                # Try to match display name to variant in metadata
                installed_match_key = (
                    stadium_variant_match_key(filename_stem)
                    if stage_code == 'GrPs'
                    else get_variant_match_key(display_name_from_file))
                for vid, vmeta in metadata_variants.items():
                    variant_display_name = vmeta.get('name', vid)
                    candidate = variant_display_name
                    if stage_code == 'GrPs':
                        if button:
                            candidate = add_button_indicator(candidate, button)
                        if installed_match_key.startswith('stadium-hash:'):
                            candidate_key = stadium_variant_hashed_match_key(candidate)
                        else:
                            candidate_key = stadium_variant_match_key(
                                stadium_runtime_variant_name(candidate))
                    else:
                        candidate_key = get_variant_match_key(candidate)
                    if candidate_key == installed_match_key:
                        variant_id_for_screenshot = vid
                        variant_meta = vmeta
                        logger.info(f"Matched display name '{display_name_from_file}' to variant_id '{vid}'")
                        break

                # Fallback: if no match in metadata, treat filename as variant_id
                if variant_id_for_screenshot is None:
                    variant_id_for_screenshot = display_name_from_file
                    variant_meta = metadata_variants.get(variant_id_for_screenshot, {})
                    logger.info(f"No metadata match for '{display_name_from_file}', using as variant_id")

                # Check if screenshot exists in storage (supports multiple extensions)
                screenshot_folder = STORAGE_PATH / 'das' / stage_folder_name
                has_screenshot, screenshot_path, screenshot_ext = find_stage_screenshot(screenshot_folder, variant_id_for_screenshot)

                variants.append({
                    'name': filename_stem,
                    'displayName': variant_meta.get('name', display_name_from_file),
                    'filename': stage_file.name,
                    'stageCode': stage_code,
                    'button': button,
                    'hasScreenshot': has_screenshot,
                    'screenshotUrl': f"/storage/das/{stage_folder_name}/{variant_id_for_screenshot}_screenshot{screenshot_ext}" if has_screenshot else None,
                    'slippi_safe': variant_meta.get('slippi_safe'),
                    'slippi_tested': variant_meta.get('slippi_tested', False)
                })

        return jsonify({
            'success': True,
            'stage': DAS_STAGES[stage_code],
            'variants': variants
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@das_bp.route('/api/mex/das/import', methods=['POST'])
def das_import_variant():
    """Import DAS variant to MEX project"""
    try:
        data = request.json
        stage_code = data.get('stageCode')
        variant_path = data.get('variantPath')

        logger.info(f"=== DAS IMPORT REQUEST ===")
        logger.info(f"Stage Code: {stage_code}")
        logger.info(f"Variant Path: {variant_path}")

        if not stage_code or not variant_path:
            return jsonify({
                'success': False,
                'error': 'Missing stageCode or variantPath parameter'
            }), 400

        if stage_code not in DAS_STAGES:
            return jsonify({
                'success': False,
                'error': f'Unknown stage code: {stage_code}'
            }), 400

        # Resolve variant path
        full_variant_path = PROJECT_ROOT / variant_path

        if not full_variant_path.exists():
            return jsonify({
                'success': False,
                'error': f'Variant ZIP not found: {variant_path}'
            }), 404

        file_ext = '.dat'

        with zipfile.ZipFile(full_variant_path, 'r') as zip_ref:
            stage_files = [f for f in zip_ref.namelist() if f.endswith('.dat') or f.endswith('.usd')]
            if not stage_files:
                return jsonify({
                    'success': False,
                    'error': 'No .dat/.usd stage file found in ZIP'
                }), 400

            transformation_members = {}
            stage_candidates = stage_files
            if stage_code == 'GrPs':
                try:
                    transformation_members = stadium_transformation_members(
                        stage_files)
                except ValueError as member_err:
                    return jsonify({'success': False,
                                    'error': str(member_err)}), 400
                if transformation_members and len(transformation_members) != 4:
                    missing = [f'GrPs{i}.dat' for i in range(1, 5)
                               if i not in transformation_members]
                    return jsonify({
                        'success': False,
                        'error': ('Per-variant Stadium transformations require '
                                  'a complete GrPs1.dat through GrPs4.dat set.'),
                        'reason': 'incomplete_stadium_transformations',
                        'missing': missing,
                    }), 400
                stage_candidates = [
                    name for name in stage_files
                    if name not in transformation_members.values()
                ]
                if not stage_candidates:
                    return jsonify({
                        'success': False,
                        'error': 'No normal Pokemon Stadium stage file found in ZIP'
                    }), 400

            stage_file, conflicting_codes = select_stage_archive_member(
                stage_candidates, stage_code)
            if stage_file is None:
                requested = DAS_STAGES[stage_code]
                detected = [DAS_STAGES[code] for code in conflicting_codes]
                if len(detected) == 1:
                    error = (
                        f"Stage archive targets {detected[0]['name']} "
                        f"({detected[0]['code']}), not {requested['name']} "
                        f"({requested['code']}). Import it under "
                        f"{detected[0]['name']} instead."
                    )
                else:
                    labels = ', '.join(
                        f"{item['name']} ({item['code']})"
                        for item in detected)
                    error = (
                        f"Archive contains stage files for {labels}, but none "
                        f"for {requested['name']} ({requested['code']})."
                    )
                return jsonify({
                    'success': False,
                    'error': error,
                    'reason': 'stage_code_mismatch',
                    'requestedStageCode': stage_code,
                    'detectedStageCodes': conflicting_codes,
                    'detectedStageCode': (conflicting_codes[0]
                                          if len(conflicting_codes) == 1
                                          else None),
                }), 400

            # Read the stage file data
            stage_data = zip_ref.read(stage_file)
            transformation_data = {
                index: zip_ref.read(member)
                for index, member in transformation_members.items()
            }

            # Do not create even an empty destination folder until the archive
            # has passed the stage-family check above.
            project_files = get_project_files_dir()
            stage_folder = project_files / stage_code
            stage_folder.mkdir(exist_ok=True)

            # Get variant_id from ZIP filename
            variant_id = Path(full_variant_path).stem

            # Load metadata to get display name
            display_name = variant_id

            metadata = load_metadata(default={})
            if metadata:
                stage_folder_name = DAS_STAGES[stage_code]['folder']
                stage_metadata = metadata.get('stages', {}).get(stage_folder_name, {})

                # Find the variant in metadata by id
                for variant in stage_metadata.get('variants', []):
                    if variant['id'] == variant_id:
                        display_name = variant.get('name', variant_id)
                        logger.info(f"Found display name in metadata: '{display_name}' for variant_id '{variant_id}'")
                        break

            # Use sanitized display name for filename
            final_name = normalize_variant_name(sanitize_filename(display_name))
            if stage_code == 'GrPs':
                final_name = stadium_runtime_variant_name(final_name)
            final_path = stage_folder / f"{final_name}{file_ext}"

            # If file already exists, append suffix to avoid conflicts
            if final_path.exists() or (stage_folder / final_name).exists():
                count = 1
                while True:
                    final_name = normalize_variant_name(f"{sanitize_filename(display_name)}_{count}")
                    if stage_code == 'GrPs':
                        final_name = stadium_runtime_variant_name(final_name)
                    final_path = stage_folder / f"{final_name}{file_ext}"
                    if (not final_path.exists()
                            and not (stage_folder / final_name).exists()):
                        break
                    count += 1

            # Stadium variants: repair transformation visibility (duplicate
            # platform/deck copies in permanent model groups linger visibly
            # during fire/grass/rock/water forms; the repair relocates them
            # into the group the engine hides with the normal form).
            transform_fix = None
            if stage_code == 'GrPs':
                from vault.importing.stadium_transform_fix import repair_stadium_variant
                try:
                    fixed, transform_fix = repair_stadium_variant(stage_data)
                    if fixed is not None:
                        stage_data = fixed
                    for line in (transform_fix.get('actions', [])
                                 + transform_fix.get('notes', [])):
                        logger.info(f"  [transform-fix] {line}")
                except Exception as fix_err:
                    logger.warning(f"  [transform-fix] skipped: {fix_err}")
                    transform_fix = {'status': 'error', 'notes': [str(fix_err)]}
                if transform_fix and transform_fix.get('status') == 'flagged':
                    # geometry is baked into permanent groups and cannot be
                    # relocated -- freezing the build's transformations is
                    # the supported way to avoid the lingering visuals
                    transform_fix['recommendation'] = 'freeze'

            # Write directly to final location
            final_path.write_bytes(stage_data)
            logger.info(f"[OK] Extracted stage file to: {final_path}")
            logger.info(f"  Using mod name: {final_name}")

            transformation_dir = None
            if transformation_data:
                transformation_dir = stage_folder / final_name
                transformation_dir.mkdir(exist_ok=False)
                for index, form_data in transformation_data.items():
                    (transformation_dir / f'GrPs{index}.dat').write_bytes(
                        form_data)
                logger.info(
                    f"[OK] Installed per-variant Stadium transformations: "
                    f"{transformation_dir}")

        logger.info(f"DAS variant imported to: {final_path}")

        result = {
            'success': True,
            'message': 'DAS variant imported successfully',
            'path': str(final_path)
        }
        if transform_fix is not None:
            result['transformFix'] = transform_fix
        if transformation_data:
            result['transformationSkins'] = {
                'status': 'installed',
                'count': 4,
                'path': str(transformation_dir),
                'layout': 'GrPs/<Variant>/GrPs1.dat..GrPs4.dat',
            }
        return jsonify(result)
    except Exception as e:
        logger.error(f"DAS import error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@das_bp.route('/api/mex/das/remove', methods=['POST'])
def das_remove_variant():
    """Remove DAS variant from MEX project"""
    try:
        data = request.json
        stage_code = data.get('stageCode')
        variant_name = data.get('variantName')

        logger.info(f"=== DAS REMOVE REQUEST ===")
        logger.info(f"Stage Code: {stage_code}")
        logger.info(f"Variant Name: {variant_name}")

        if not stage_code or not variant_name:
            return jsonify({
                'success': False,
                'error': 'Missing stageCode or variantName parameter'
            }), 400

        if stage_code not in DAS_STAGES:
            return jsonify({
                'success': False,
                'error': f'Unknown stage code: {stage_code}'
            }), 400

        file_ext = '.dat'
        project_files = get_project_files_dir()
        stage_folder = project_files / stage_code
        variant_path = direct_variant_child(
            stage_folder, f"{variant_name}{file_ext}")
        transformation_dir = direct_variant_child(stage_folder, variant_name)

        if not variant_path.exists():
            return jsonify({
                'success': False,
                'error': f'Variant not found: {variant_name}{file_ext}'
            }), 404

        if transformation_dir.is_dir():
            shutil.rmtree(transformation_dir)
            logger.info(
                f"DAS variant transformations removed: {transformation_dir}")
        variant_path.unlink()
        logger.info(f"DAS variant removed: {variant_path}")

        return jsonify({
            'success': True,
            'message': 'DAS variant removed successfully'
        })
    except Exception as e:
        logger.error(f"DAS remove error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@das_bp.route('/api/mex/das/rename', methods=['POST'])
def das_rename_variant():
    """
    Rename a DAS variant file (e.g., add/remove button indicator)

    Body:
    {
      "stageCode": "GrOp",
      "oldName": "vanilla",
      "newName": "Vanilla(B)"
    }
    """
    try:
        data = request.json
        stage_code = data.get('stageCode')
        old_name = data.get('oldName')
        new_name = normalize_variant_name(data.get('newName'))
        if stage_code == 'GrPs':
            new_name = stadium_runtime_variant_name(new_name)

        logger.info(f"DAS Rename Request - Stage: {stage_code}, Old: {old_name}, New: {new_name}")

        if not stage_code or not old_name or not new_name:
            return jsonify({
                'success': False,
                'error': 'Missing stageCode, oldName, or newName parameter'
            }), 400

        if stage_code not in DAS_STAGES:
            return jsonify({
                'success': False,
                'error': f'Unknown stage code: {stage_code}'
            }), 400

        file_ext = '.dat'
        project_files = get_project_files_dir()
        stage_folder = project_files / stage_code

        old_path = direct_variant_child(stage_folder, f"{old_name}{file_ext}")
        new_path = direct_variant_child(stage_folder, f"{new_name}{file_ext}")
        old_transformations = direct_variant_child(stage_folder, old_name)
        new_transformations = direct_variant_child(stage_folder, new_name)

        if not old_path.exists():
            return jsonify({
                'success': False,
                'error': f'Source file not found: {old_name}{file_ext}'
            }), 404

        if new_path.exists() or new_transformations.exists():
            return jsonify({
                'success': False,
                'error': f'Target file already exists: {new_name}{file_ext}'
            }), 409

        # Rename the file
        old_path.rename(new_path)
        try:
            if old_transformations.is_dir():
                old_transformations.rename(new_transformations)
        except Exception:
            # Keep the normal archive and its sidecars attached if moving the
            # companion directory fails for any reason.
            new_path.rename(old_path)
            raise
        logger.info(f"DAS variant renamed: {old_path} -> {new_path}")

        return jsonify({
            'success': True,
            'message': 'DAS variant renamed successfully',
            'oldName': old_name,
            'newName': new_name
        })
    except Exception as e:
        logger.error(f"DAS rename error: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
