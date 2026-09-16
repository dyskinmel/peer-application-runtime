"""Real temporary-file mutation and allocation tests for the shared bounded reader."""
import os, tempfile, tracemalloc, unittest
from pathlib import Path
from unittest.mock import patch
from par_recovery import transfer

class SnapshotIO(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.path=self.root/'record';self.path.write_bytes(b'public record')
    def tearDown(self):self.tmp.cleanup()
    def rejected(self,fn):
        with self.assertRaises(transfer.E):fn()
    def intercepted(self,before=None,after=None,sizes=None):
        original=transfer.os.fdopen
        class File:
            def __init__(self,fd,mode):self.file=original(fd,mode)
            def __enter__(self):return self
            def __exit__(self,*a):self.file.close()
            def fileno(self):return self.file.fileno()
            def read(self,n):
                if sizes is not None:sizes.append(n)
                if before:before()
                raw=self.file.read(n)
                if after:after()
                return raw
        return patch.object(transfer.os,'fdopen',File)
    def test_small_file_does_not_allocate_limit(self):
        tracemalloc.start()
        try:
            self.assertEqual(transfer.read_file(self.path,16*1024*1024),b'public record');current,peak=tracemalloc.get_traced_memory()
        finally:tracemalloc.stop()
        self.assertLess(peak,1024*1024,'small file read must not allocate the 16MiB limit')
    def test_read_bound_uses_observed_size_plus_one(self):
        sizes=[]
        with self.intercepted(sizes=sizes):self.assertEqual(transfer.read_file(self.path,16*1024*1024),b'public record')
        self.assertEqual(sizes,[len(b'public record')+1])
    def test_growth_between_stat_and_read_rejected(self):
        with self.intercepted(before=lambda:self.path.write_bytes(b'public record!')):self.rejected(lambda:transfer.read_file(self.path))
    def test_truncation_between_stat_and_read_rejected(self):
        with self.intercepted(before=lambda:self.path.write_bytes(b'p')):self.rejected(lambda:transfer.read_file(self.path))
    def test_same_size_mutation_after_read_rejected(self):
        with self.intercepted(after=lambda:self.path.write_bytes(b'changed value')):self.rejected(lambda:transfer.read_file(self.path))
    def test_path_replacement_after_read_rejected(self):
        replacement=self.root/'new';replacement.write_bytes(self.path.read_bytes())
        with self.intercepted(after=lambda:os.replace(replacement,self.path)):self.rejected(lambda:transfer.read_file(self.path))
    def test_same_mtime_rewrite_not_trusted(self):
        st=self.path.stat()
        def mutate():self.path.write_bytes(b'changed value');os.utime(self.path,ns=(st.st_atime_ns,st.st_mtime_ns))
        with self.intercepted(after=mutate):self.rejected(lambda:transfer.read_file(self.path))
    def test_maximum_valid_file_reads_exact_bytes(self):
        raw=b'a'*65536;self.path.write_bytes(raw);self.assertEqual(transfer.read_file(self.path,len(raw)),raw)
    def test_over_limit_rejected(self):self.rejected(lambda:transfer.read_file(self.path,1))
    def test_empty_file_rejected(self):self.path.write_bytes(b'');self.rejected(lambda:transfer.read_file(self.path))
    def test_symlink_rejected(self):
        link=self.root/'link';link.symlink_to(self.path);self.rejected(lambda:transfer.read_file(link))
    def test_missing_file_rejected(self):self.path.unlink();self.rejected(lambda:transfer.read_file(self.path))
