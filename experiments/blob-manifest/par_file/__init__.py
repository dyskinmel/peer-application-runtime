"""Whole-file local contract experiment. No product or network qualification."""
from .errors import FileError
from . import manifest
__all__=['FileError','manifest']
from .writer import FileWriter,StagedFile
from .reader import export_file,inspect_file,FileInfo
__all__ += ['FileWriter','StagedFile','export_file','inspect_file','FileInfo']
