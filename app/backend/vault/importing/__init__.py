"""Bring mods INTO the vault: detect what a DAT/zip/ISO is, rip content out
of ISOs, convert legacy formats. `vault/routes/import_unified/` is the HTTP
front; these are the engines.

  unified/                                    the import endpoint's engine: detection,
                                              normalization, per-kind importers, archive dispatch

  character_detector.py / stage_detector.py   identify character, costume, stage
  iso_scanner.py                              walk a GC ISO, rip costumes/stages
  das_scan.py                                 Dynamic Alternate Stages variant detection
  fighter_yml_converter.py / stage_yml_converter.py   classic mexTool formats
  vanilla_stage_import.py (+ _specs)          a lone GrXx.dat -> ADDED stage
  custom_stage_package.py                     a stage package ZIP -> vault custom stage
  sound_banks.py                              vanilla sound banks (.ssm) per character; first-run seeding
"""
