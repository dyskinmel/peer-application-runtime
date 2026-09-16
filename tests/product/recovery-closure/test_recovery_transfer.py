from recovery_support import *
class Transfer(RecoveryTest):
    def inbox(self,b,**kw):return self.rc.Inbox(Path(self.tmp.name)/'inbox',b.index,self.pin(b),**kw)
    def test_transfer_api_exists(self):self.assertTrue(hasattr(self.rc,'Inbox'),'resumable recipient Inbox not implemented')
    def test_missing_then_complete(self):
        b=self.collect()
        with self.inbox(b) as rx:
            self.assertEqual(set(rx.missing()),set(b.objects))
            for oid,raw in b.objects.items():self.assertEqual(rx.put(oid,raw),'ACCEPTED')
            self.assertEqual(rx.missing(),());self.assertEqual(rx.status()['state'],'BYTES_COMPLETE')
            self.assertFalse(rx.status()['recipient_validated'])
    def test_duplicate_is_exact(self):
        b=self.collect();oid=next(iter(b.objects))
        with self.inbox(b) as rx:
            rx.put(oid,b.objects[oid]);self.assertEqual(rx.put(oid,b.objects[oid]),'DUPLICATE')
    def test_wrong_bytes_rejected(self):
        b=self.collect();oid=next(iter(b.objects))
        with self.inbox(b) as rx:self.reject_rc('OBJECT_HASH',lambda:rx.put(oid,b'x'))
    def test_unknown_id_rejected(self):
        b=self.collect()
        with self.inbox(b) as rx:self.reject_rc('OBJECT_REFERENCE',lambda:rx.put(h('alien'),b'x'))
    def test_path_string_not_id(self):
        b=self.collect()
        with self.inbox(b) as rx:self.reject_rc(None,lambda:rx.put('../../escape',b'x'))
    def test_resume_recovers_completed_files(self):
        b=self.collect();oid=next(iter(b.objects))
        with self.inbox(b) as rx:rx.put(oid,b.objects[oid])
        with self.inbox(b) as rx:self.assertNotIn(oid,rx.missing())
    def test_resume_rehashes_completed_bytes(self):
        b=self.collect();oid=next(iter(b.objects))
        with self.inbox(b) as rx:rx.put(oid,b.objects[oid])
        (Path(self.tmp.name)/'inbox/objects'/oid.hex()).write_bytes(b'bad')
        self.reject_rc('OBJECT_HASH',lambda:self.inbox(b))
    def test_resume_rejects_other_pin(self):
        b=self.collect()
        with self.inbox(b):pass
        self.reject_rc('PIN_MISMATCH',lambda:self.rc.Inbox(Path(self.tmp.name)/'inbox',b.index,replace(self.pin(b),head=h('bad'))))
    def test_resume_rejects_other_index(self):
        b=self.collect()
        with self.inbox(b):pass
        p=Path(self.tmp.name)/'inbox/index.cbor';p.write_bytes(b'bad')
        self.reject_rc('INDEX_CHANGED',lambda:self.inbox(b))
    def test_unknown_staged_file_rejected(self):
        b=self.collect()
        with self.inbox(b):pass
        (Path(self.tmp.name)/'inbox/objects/extra').write_bytes(b'bad')
        self.reject_rc('UNEXPECTED_FILE',lambda:self.inbox(b))
    def test_symlink_root_rejected(self):
        b=self.collect();Path(self.tmp.name,'inbox').symlink_to(self.root,target_is_directory=True)
        self.reject_rc('UNSAFE_PATH',lambda:self.inbox(b))
    def test_symlink_object_rejected(self):
        b=self.collect();oid=next(iter(b.objects))
        with self.inbox(b):pass
        (Path(self.tmp.name)/'inbox/objects'/oid.hex()).symlink_to(self.source)
        self.reject_rc('UNSAFE_PATH',lambda:self.inbox(b))
    def test_second_writer_rejected(self):
        b=self.collect()
        with self.inbox(b):self.reject_rc('WRITER_BUSY',lambda:self.inbox(b))
    def test_closed_inbox_rejects(self):
        b=self.collect();rx=self.inbox(b);rx.close()
        self.reject_rc('CLOSED',lambda:rx.missing())
    def test_partial_pull(self):
        b=self.collect();source=self.publish(b);p=self.rc.DirectoryProvider(source,b.index,self.pin(b))
        with self.inbox(b) as rx:
            result=rx.pull(p,limit=2);self.assertEqual(result['received'],2);self.assertEqual(len(rx.missing()),len(b.objects)-2)
    def test_provider_missing_not_completed(self):
        b=self.collect();source=self.publish(b);oid=next(iter(b.objects));(source/'objects'/oid.hex()).unlink()
        with self.inbox(b) as rx:
            rx.pull(self.rc.DirectoryProvider(source,b.index,self.pin(b)),limit=1024);self.assertEqual(rx.missing(),(oid,))
    def test_provider_corrupt_rejected(self):
        b=self.collect();source=self.publish(b);oid=next(iter(b.objects));(source/'objects'/oid.hex()).write_bytes(b'bad')
        with self.inbox(b) as rx:self.reject_rc('OBJECT_HASH',lambda:rx.pull(self.rc.DirectoryProvider(source,b.index,self.pin(b)),limit=1024))
    def test_incomplete_cannot_publish(self):
        b=self.collect();dest=Path(self.tmp.name)/'recovered'
        with self.inbox(b) as rx:self.reject_rc('OBJECT_SET',lambda:rx.finalize(dest,self.p,self.reader['secret']))
        self.assertFalse(dest.exists())
    def test_wrong_recipient_cannot_publish(self):
        b=self.collect();dest=Path(self.tmp.name)/'recovered'
        with self.inbox(b) as rx:
            for i,raw in b.objects.items():rx.put(i,raw)
            self.reject_rc('RECIPIENT_CRYPTO',lambda:rx.finalize(dest,self.p,h('wrong')))
        self.assertFalse(dest.exists())
    def test_publish_then_reopen_export(self):
        b=self.collect();dest=Path(self.tmp.name)/'recovered'
        with self.inbox(b) as rx:
            for i,raw in b.objects.items():rx.put(i,raw)
            v=rx.finalize(dest,self.p,self.reader['secret']);self.assertFalse(v.status()['writable'])
        v=self.rc.open_recovery(dest,self.pin(b),self.p,self.reader['secret']);v.export_file(self.receipt.envelope_id,self.output)
        self.assertEqual(self.output.read_bytes(),self.data)
    def test_does_not_copy_database_or_local_cache(self):
        b=self.collect();root=self.publish(b)
        self.assertEqual({p.name for p in root.iterdir()},{'index.cbor','objects','.store.lock'})
        self.assertFalse(any(p.suffix in ('.db','.sqlite') for p in root.rglob('*')))
        for raw in b.objects.values():self.assertNotIn(self.s.secret,raw)
    def test_existing_destination_unchanged(self):
        b=self.collect();dest=Path(self.tmp.name)/'recovered';dest.mkdir();(dest/'keep').write_bytes(b'keep')
        with self.inbox(b) as rx:
            for i,raw in b.objects.items():rx.put(i,raw)
            self.reject_rc('DESTINATION_EXISTS',lambda:rx.finalize(dest,self.p,self.reader['secret']))
        self.assertEqual((dest/'keep').read_bytes(),b'keep')
    def test_pull_limit_must_be_positive(self):
        b=self.collect()
        with self.inbox(b) as rx:self.reject_rc('TRANSFER_LIMIT',lambda:rx.pull(None,limit=0))
    def test_corrupt_recovered_object_not_trusted(self):
        b=self.collect();dest=self.publish(b);oid=next(iter(b.objects));(dest/'objects'/oid.hex()).write_bytes(b'bad')
        self.reject_rc('OBJECT_HASH',lambda:self.rc.open_recovery(dest,self.pin(b),self.p,self.reader['secret']))
    def test_existing_empty_directory_not_silently_replaced(self):
        b=self.collect();dest=Path(self.tmp.name)/'empty';dest.mkdir()
        with self.inbox(b) as rx:
            for i,raw in b.objects.items():rx.put(i,raw)
            self.reject_rc('DESTINATION_EXISTS',lambda:rx.finalize(dest,self.p,self.reader['secret']))
    def test_closed_put_does_not_publish(self):
        b=self.collect();rx=self.inbox(b);rx.close();oid=next(iter(b.objects))
        self.reject_rc('CLOSED',lambda:rx.put(oid,b.objects[oid]))
    def test_missing_acknowledged_file_becomes_missing_not_complete(self):
        b=self.collect();oid=next(iter(b.objects))
        with self.inbox(b) as rx:
            for i,raw in b.objects.items():rx.put(i,raw)
        (Path(self.tmp.name)/'inbox/objects'/oid.hex()).unlink()
        with self.inbox(b) as rx:self.assertEqual(rx.status()['state'],'MISSING_OBJECTS');self.assertIn(oid,rx.missing())
    def test_provider_index_changed_during_receive(self):
        b=self.collect();root=self.publish(b);p=self.rc.DirectoryProvider(root,b.index,self.pin(b))
        (root/'index.cbor').write_bytes(b'bad');self.reject_rc('INDEX_CHANGED',lambda:p.fetch(next(iter(b.objects))))
    def test_provider_unknown_object_request_refused(self):
        b=self.collect();root=self.publish(b);p=self.rc.DirectoryProvider(root,b.index,self.pin(b))
        self.reject_rc('OBJECT_REFERENCE',lambda:p.fetch(h('unknown')))
    def test_stage_object_mode_is_private(self):
        import stat
        b=self.collect();oid=next(iter(b.objects))
        with self.inbox(b) as rx:rx.put(oid,b.objects[oid])
        self.assertEqual(stat.S_IMODE((Path(self.tmp.name)/'inbox/objects'/oid.hex()).stat().st_mode),0o600)
    def test_validated_view_owns_input_bytes(self):
        b=self.collect();view=self.verify(b);b.objects.clear()
        view.export_file(self.receipt.envelope_id,self.output);self.assertEqual(self.output.read_bytes(),self.data)
    def test_writable_status_never_loaded_from_disk(self):
        b=self.collect();root=self.publish(b);self.assertFalse(self.rc.open_recovery(root,self.pin(b),self.p,self.reader['secret']).status()['writable'])
