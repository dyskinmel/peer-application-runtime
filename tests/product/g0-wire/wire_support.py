from pathlib import Path
import copy, importlib, importlib.util, sys, unittest
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'experiments/g0-wire'))
ID=bytes(range(32)); OTHER=bytes(range(32,64)); RID=bytes(range(16)); SIG=b's'*64
BODIES={
 1:{0:'org.example.notes',1:b'cert',2:ID,3:['par/1-draft-2'],4:[1],5:OTHER,6:b'peer-a'},
 2:{0:ID,1:SIG},
 10:{0:ID,1:b'proof',2:None,3:1,4:OTHER,5:SIG,6:[]},
 11:{0:ID,1:1,2:1,3:OTHER,4:SIG},
 12:{0:None,1:1,2:None},
 13:{0:ID,1:[b'entry'],2:None,3:True},
 20:{0:ID,1:None,2:[{0:ID,1:1,2:1,3:[OTHER],4:False,5:OTHER}],3:True},
 21:{0:ID,1:[OTHER]},22:{0:ID,1:OTHER,2:b'change'},
 23:{0:ID,1:0,2:[OTHER],3:None},30:{0:ID,1:OTHER},31:{0:ID,1:b'manifest'},
 32:{0:ID,1:OTHER,2:ID},33:{0:ID,1:b'block'},
 40:{0:RID,1:ID,2:b'manifest',3:60,4:123,5:OTHER},
 41:{0:RID,1:60,2:[ID],3:None,4:True},42:{0:RID,1:ID,2:OTHER},
 43:{0:b'receipt'},44:{0:RID,1:ID,2:False,3:OTHER},45:{0:RID,1:0,2:'released'},
 50:{0:ID,1:1,2:30,3:b'hint'},60:{0:RID,1:ID,2:'thumbnail',3:OTHER,4:b'',5:1000,6:0},
 61:{0:RID,1:0,2:b'',3:None},62:{0:RID},63:{0:RID,1:0},
 255:{0:1001,1:'decode',2:0,3:'invalid'},
}
def sample(code):return {0:1,1:code,2:RID,3:None if code in (1,2,255) else ID,4:copy.deepcopy(BODIES[code]),5:0}
class WireCase(unittest.TestCase):
 def mod(self,name):
  spec=importlib.util.find_spec('par_wire')
  self.assertIsNotNone(spec,'G0 wire package has not been implemented')
  spec=importlib.util.find_spec('par_wire.'+name)
  self.assertIsNotNone(spec,'G0 '+name+' has not been implemented')
  return importlib.import_module('par_wire.'+name)
 def reject(self,code,fn,*a,**kw):
  with self.assertRaises(ValueError) as cm:fn(*a,**kw)
  self.assertEqual(cm.exception.code,code,str(cm.exception))
