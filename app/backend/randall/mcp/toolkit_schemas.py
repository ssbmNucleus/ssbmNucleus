"""The creation toolkit's two tools as the developer harness defines them, copied here as static data.

``native_port`` (tools/creation/workflows.py) and ``stage_workbench`` (tools/harness/harness_mcp.py) run in a
source checkout, never in the app (randall/mcp/toolkit.py forwards to one). The app must not import tools/, so their
descriptions and inputSchemas are copied verbatim; tests/tools/test_app_mcp_toolkit_schemas.py fails when the
harness changes and this copy was not refreshed (regenerate it from ``harness_mcp.TOOL_DEFS``).
"""

TOOLS = [{'name': 'native_port',
  'description': "Build native fighters with Nucleus's port engine and Slap City/Rivals 2 readers. Start op=info. "
                 'Builds/readers/adapters return a durable job; follow it with op=status and job, which waits for it '
                 'to end (wait_seconds) so it needs no sleeping between calls. op=inspect reads work receipts. Ports '
                 'retain implementation limitations; gameplay calibration is optional.',
  'inputSchema': {'type': 'object',
                  'properties': {'op': {'type': 'string',
                                        'enum': ['info',
                                                 'read_source',
                                                 'port',
                                                 'inspect',
                                                 'checklist',
                                                 'adapter',
                                                 'status',
                                                 'cancel']},
                                 'job': {'type': 'string'},
                                 'wait_seconds': {'type': 'integer',
                                                  'minimum': 0,
                                                  'maximum': 40,
                                                  'description': 'op=status only: wait up to this many seconds for the '
                                                                 'job to end (default 30), so call status again at '
                                                                 'once, without sleeping'},
                                 'game': {'type': 'string', 'enum': ['ultimate', 'brawl', 'slapcity', 'rivals2']},
                                 'fighter': {'type': 'string',
                                             'description': 'Source identifier; reader uses Rivals capitalization '
                                                            '(Ranno), port uses lowercase (ranno)'},
                                 'name': {'type': 'string'},
                                 'donor': {'type': 'string'},
                                 'work': {'type': 'string',
                                          'description': 'Dedicated absolute port work folder. Existing work '
                                                         'resumes/rebuilds selected stages.'},
                                 'root': {'type': 'string',
                                          'description': 'Absolute source root. For read_source, a NEW output folder.'},
                                 'game_dir': {'type': 'string',
                                              'description': 'Slap City_Data or Rivals 2 installation; read_source '
                                                             'only'},
                                 'list': {'type': 'boolean'},
                                 'own': {'type': 'boolean'},
                                 'body': {'type': 'string'},
                                 'rip': {'type': 'string'},
                                 'iso': {'type': 'string'},
                                 'mextk': {'type': 'string'},
                                 'from': {'type': 'string'},
                                 'to': {'type': 'string'},
                                 'only': {'type': 'string'},
                                 'forms_from': {'type': 'string'},
                                 'calibrate': {'type': 'boolean',
                                               'description': 'Optional developer gameplay calibration; default false'},
                                 'tests': {'type': 'array', 'items': {'type': 'string'}},
                                 'allow_large': {'type': 'boolean'},
                                 'line': {'type': 'string'},
                                 'answer': {'type': 'string'},
                                 'how': {'type': 'string'},
                                 'operation': {'type': 'string',
                                               'enum': ['audit',
                                                        'movement_audit',
                                                        'movement_repair',
                                                        'hitbox_rebase',
                                                        'source_combat_audit',
                                                        'source_combat_install',
                                                        'compress',
                                                        'scale',
                                                        'materials',
                                                        'costume',
                                                        'visibility',
                                                        'pack',
                                                        'preflight',
                                                        'plan_rig',
                                                        'source_visibility',
                                                        'costume_budget',
                                                        'animation_diagnose']},
                                 'options': {'type': 'object',
                                             'description': 'Arguments for the selected advanced port_mcp adapter; '
                                                            'absolute file paths'}},
                  'additionalProperties': False}},
 {'name': 'stage_workbench',
  'description': 'Freeform custom stage authoring. Start with op=guide. Promoted Colosseum/CS2 primitives, not a fixed '
                 'design recipe: inspect DAT/scene_data groups and animations; mesh converts triangle JSON + PNG; '
                 'graft builds a new DAT from a flexible spec (3D animated donors and/or custom meshes); cameras '
                 'returns real-match framing estimates; package writes a verified ZIP. Paths must be absolute; '
                 'relative spec assets resolve beside the spec. Outputs must be new revisions. No automatic vault '
                 'install, ISO build or gameplay test. Native inspect/graft needs .NET SDK and configured HSDRaw. See '
                 'tools/stages/README.md.',
  'inputSchema': {'type': 'object',
                  'properties': {'op': {'type': 'string',
                                        'enum': ['guide', 'inspect', 'mesh', 'graft', 'cameras', 'package']},
                                 'file': {'type': 'string', 'description': 'DAT/USD/RDAT for inspect'},
                                 'spec': {'type': 'string',
                                          'description': 'JSON file for graft or mesh; guide documents formats'},
                                 'out': {'type': 'string',
                                         'description': 'New output DAT/ZIP/sweep JSON, or mesh filename prefix'},
                                 'stage': {'type': 'string',
                                           'description': 'Optional camera/budget preset: '
                                                          'battlefield|final|fountain|dreamland|stadium|yoshis (long '
                                                          'names also accepted)'},
                                 'camera': {'type': 'object',
                                            'description': 'Optional custom StageCameraInfo constants; see guide'},
                                 'views': {'type': 'array',
                                           'items': {'type': 'object'},
                                           'description': 'Optional camera views [{name,box:[xmin,ymin,xmax,ymax]}] in '
                                                          'world units'},
                                 'files': {'type': 'object',
                                           'additionalProperties': {'type': 'string'},
                                           'description': 'package: ZIP filename -> absolute source path'}},
                  'required': []}}]
