"""Stage file naming and the vanilla stage dat location for Randall's stage editor."""
from core.config import STORAGE_PATH

STAGE_DATS_DIR = STORAGE_PATH / 'skinlab_stages'

# NTSC loads localized .usd files for stages with on-screen text. Stadium's
# jumbotron is English only in GrPs.usd -- basing variants on GrPs.dat ships
# the Japanese stage (and a DIFFERENT texture enumeration, which broke the
# region map). Community DAS variants all ship GrPs.usd.
STAGE_FILE_EXT = {'GrPs': '.usd'}


def stage_file_name(code):
    return f"{code}{STAGE_FILE_EXT.get(code, '.dat')}"
