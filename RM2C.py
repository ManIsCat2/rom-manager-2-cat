import sys, os, struct, shutil, math, re, gc, time, cProfile, pstats
import GeoWrite as GW
import F3D
import ColParse
from pathlib import Path
from capstone import *
from bitstring import *
from RM2CData import *
import BinPNG
import groups as GD
import disassemble_sound as d_s
import multiprocessing as mp
import BhvParse as BP
import Log
#these all exist as data modules for comparisons to see if content is new or not
import ActorCHKSM
import BehComp
import ColComp

#So that each Script class doesn't open up a half MB file.
mapF = open('sm64.us.map','r')
map = mapF.readlines()

Seg2Location = 0x800000
Seg2LocationEnd = Seg2Location + 0x3156
Seg15Location = 0x2ABCA0
RomDataGlobal = None

class Script():
	def __init__(self,level):
		global map
		self.map=map
		self.banks=[None for a in range(32)]
		self.asm=[[0x80400000,0x1200000,0x1220000],[0x80246000,0x1000,0x21f4c0]]
		self.models=[None for a in range(256)]
		self.Currlevel=level
		self.levels={}
		self.levels[self.Currlevel]=[None for a in range(8)]
		self.texScrolls=False
		self.verts = []
		#stack is simply a stack of ptrs
		#base is the prev pos
		#top is the current pos
		self.Base=None
		self.Stack=[]
		self.Top=-1
		self.CurrArea=None
		self.header=[]
		self.objects = []
		self.ScrollArray=[]
		# setup segments
		UPH2 = (lambda rom,addr: struct.unpack(">I", rom[addr:addr+4])[0])
		global RomDataGlobal
		global Seg15Location
		global Seg2Location
		global Seg2LocationEnd
		self.banks[0x15] = [Seg15Location, UPH2(RomDataGlobal, 0x2A6230)]
		tempSeg2Loc = Seg2Location
		if Seg2Location==0x02000000:
			tempSeg2Loc=0x800000
		self.banks[0x2] = [tempSeg2Loc+0x3156, Seg2LocationEnd+0x3156]
	def B2P(self,B):
		Bank=(B>>24)
		offset=B&0xFFFFFF
		if Bank==0:
			if offset>0x400000 and offset<0x420000:
				return 0x1200000+(B&0xFFFFF)
			else:
				#check for MOP models
				if offset>0x5F0000 and offset<0x620000:
					return offset+0x1E0000
				#Its some random garbage nice
				return offset
		seg = None
		try:
			seg = self.banks[Bank]
		except:
			print("Bank", Bank, "isn't loaded yet!")
		if not seg:
			print(hex(B),hex(Bank),self.banks[Bank-2:Bank+3])
			raise "Unknown Segment."
		return seg[0]+offset
	def L4B(self,T):
		x=0
		for i,b in enumerate(T):
			x+=b<<(8*(3-i))
		return x
	def GetArea(self):
		try:
			return self.levels[self.Currlevel][self.CurrArea]
		except:
			return None
	def GetNumAreas(self,level):
		count=[]
		for i,area in enumerate(self.levels[level]):
			if area:
				count.append(i)
		return count
	def GetLabel(self,addr):
		#behavior is in bank 0 and won't be in map ever
		# if addr[0:2]=='00':
			# print(addr + ' is in bank 0 cannot be found')
			# return '0x'+addr
		for l in self.map:
			if addr in l:
				q = l.rfind(" ")
				return l[q:-1]
		return "0x"+addr
	def GetAddr(self,label):
		for l in self.map:
			if label in l:
				return "0x"+l.split("0x")[1][8:16]
		return None
	def RME(self,num,rom):
		if self.editor:
			return
		start=self.B2P(0x19005f00)
		start=TcH(rom[start+num*16:start+num*16+4])
		end=TcH(rom[start+4+num*16:start+num*16+8])
		self.banks[0x0e]=[start,end]
	def MakeDec(self,name):
		self.header.append(name)
class Area():
		def __init__(self):
			pass

def GetlevelName(lvl):
	name = ""
	try:
		name = Num2Name[lvl]
	except:
		name = "ext_level"+str(lvl)
	return name

#tuple convert to hex
def TcH(bytes):
	a = struct.pack(">%dB"%len(bytes),*bytes)
	if len(bytes)==4:
		return struct.unpack(">L",a)[0]
	if len(bytes)==2:
		return struct.unpack(">H",a)[0]
	if len(bytes)==1:
		return struct.unpack(">B",a)[0]

def U2S(half):
	return struct.unpack(">h",struct.pack(">H",half))[0]

def LoadRawJumpPush(rom,cmd,start,script):
	arg=cmd[2]
	bank=arg[0:2]
	begin = arg[2:6]
	end = arg[6:10]
	jump = arg[10:14]
	script.banks[TcH(bank)]=[TcH(begin),TcH(end)]
	script.Stack.append(start)
	script.Top+=1
	script.Stack.append(script.Base)
	script.Top+=1
	script.Base=script.Top
	return script.B2P(TcH(jump))

def LoadRawJump(rom,cmd,start,script):
	arg=cmd[2]
	bank=arg[0:2]
	begin = arg[2:6]
	end = arg[6:10]
	jump = arg[10:14]
	script.banks[TcH(bank)]=[TcH(begin),TcH(end)]
	script.Top=script.Base
	return script.B2P(TcH(jump))

def Exit(rom,cmd,start,script):
	script.Top=script.Base
	script.Base=script.Stack[script.Top]
	script.Stack.pop()
	script.Top-=1
	start=script.Stack[script.Top]
	script.Stack.pop()
	script.Top-=1
	return start

def JumpRaw(rom,cmd,start,script):
	arg=cmd[2]
	return script.B2P(TcH(arg[2:6]))

def JumpPush(rom,cmd,start,script):
	script.Top+=1
	script.Stack.append(start)
	arg=cmd[2]
	return script.B2P(TcH(arg[2:6]))

def Pop(rom,cmd,start,script):
	start=script.Stack[script.Top]
	script.Top-=1
	script.Stack.pop()
	return start

def CondPop(rom,cmd,start,script):
	#this is where the script loops
	#Ill assume no custom shit is done
	#meaning this will always signal end of level
	return None

def CondJump(rom,cmd,start,script):
	arg=cmd[2]
	level=arg[2:6]
	jump=arg[6:10]
	if script.Currlevel==TcH(level):
		return script.B2P(TcH(jump))
	else:
		return start

def SetLevel(rom,cmd,start,script):
	#gonna ignore this and take user input instead
	#script.Currlevel=TcH(cmd[2])
	# if not script.levels.get("Currlevel"):
		# script.levels[script.Currlevel]=[None for a in range(8)]
	return start

def LoadAsm(rom,cmd,start,script):
	arg=cmd[2]
	ram=arg[2:6]
	begin=arg[6:10]
	end=arg[10:14]
	Q=[TcH(ram),TcH(begin),TcH(end)]
	if Q not in script.asm:
		script.asm.append(Q)
	return start

def LoadData(rom,cmd,start,script):
	arg=cmd[2]
	bank=arg[1:2]
	begin = arg[2:6]
	end = arg[6:10]
	script.banks[TcH(bank)]=[TcH(begin),TcH(end)]
	return start

def LoadMio0(rom,cmd,start,script):
	pass

def LoadMio0Tex(rom,cmd,start,script):
	return LoadData(rom,cmd,start,script)

def StartArea(rom,cmd,start,script):
	#ignore stuff in bank 0x14 because thats star select/file select and messes up export
	arg=cmd[2]
	if TcH(arg[2:3])==0x14:
		return start
	area=arg[0]+script.Aoffset
	script.CurrArea=area
	q=Area()
	q.geo=script.B2P(TcH(arg[2:6]))
	q.objects=[]
	q.warps=[]
	q.rom=rom
	script.levels[script.Currlevel][script.CurrArea]=q
	return start

def EndArea(rom,cmd,start,script):
	script.CurrArea=None
	return start

def LoadPolyF3d(rom,cmd,start,script):
	arg=cmd[2]
	id=arg[1:2]
	layer=TcH(arg[0:1])>>4
	f3d=TcH(arg[2:6])
	script.models[TcH(id)]=(f3d,'f3d',layer,script.B2P(f3d),script)
	return start

def LoadPolyGeo(rom,cmd,start,script):
	arg=cmd[2]
	id=arg[1:2]
	geo=TcH(arg[2:6])
	script.models[TcH(id)]=(geo,'geo',None,script.B2P(geo),script)
	return start

#yep, this is what rock bottom coding looks like
ScrollCount=0
def ConvertTexScrolls(script,Obj,rom):
	if script.editor:
		return ConvertEditorTexScrolls(script,Obj,rom)
	else:
		return ConvertRMTexScrolls(script,Obj,rom)

def ConvertRMTexScrolls(script,Obj,rom):
	# RM rules
	# Verts addr = bparam
	# Verts axis = Y&0xF000 (0x8000 - Y, 0xA000 - X, 0x4000 - Z, 0x2000 - Y, 0x0000 - X)
	# Scroll Type = Y&0F00 (0x000 - normal, 0x0100 - sine, 0x0200 - jumping)
	# Speed= Z pos
	# NumVerts = X
	Addr=int(Obj[7],16)
	Num=Obj[1]
	Speed = Obj[3]
	dir = Obj[2]
	# cycle = Obj[]
	Bhvs = {
	0xA000:'x',
	0x8000:'y',
	0x4000:'xPos',
	0x2000:'yPos',
	0x0000:'zPos'
	}
	Types = {
	0x0:'normal',
	0x100:'sine',
	0x200:'jumping'
	}
	if script.texScrolls:
		script.texScrolls.append([Obj,script.CurrArea,Addr,Num,Speed,Bhvs[dir&0xF000],Types[dir&0xF00],dir&0xFF])
	else:
		script.texScrolls = [[Obj,script.CurrArea,Addr,Num,Speed,Bhvs[dir&0xF000],Types[dir&0xF00],dir&0xFF]]
	return Obj

def DetScrollType(rom):
	a=struct.unpack(">L",rom[0x1202400:0x1202404])[0]
	#false means the old, aka original version
	if a==0x27bdffe8:
		return False
	else:
		return True

def ConvertEditorTexScrolls(script,Obj,rom):
	# Editor rules
	# Verts scrolled = 0x0E000000+(Byte2(Zpos)-2)<<16+(bparam>>16)
	# Verts addr = Verts scrolled&0xFFFFFFF0
	# Verts axis = Verts scrolled&0xF (0x8 = x, 0xA = y)
	# Num verts scrolled = Byte2(Zpos)*3
	# Speed=Byte2(Zpos)
	# I have zero clue if this is true for all editor versions
	# it likely isn't
	PosByte = (lambda x: struct.pack('>f',x)[1])
	#Addr = 0x8040+PosByte+Bparam1+2. Seg E starts at 0x8045 always??
	if 'editor_Scroll_Texture2' in Obj[-2]:
		Obj[-2] = 'editor_Scroll_Texture'
	#check for other behavior type
	else:
		if DetScrollType(rom):
			return ConvertEditorTexScrollsAlt(script,Obj,PosByte)
	Addr=0x0E000000+((PosByte(Obj[1])-2)<<16)+(int(Obj[7],16)>>16) #x
	if Obj[2]:
		Num=PosByte(Obj[2])*3 #y
	else:
		Num=0 #different scroll type idk theres too many types of scrolls
	Speed = PosByte(Obj[3]) #z
	dir = Addr&0xF
	if dir==0x8:
		dir='x'
	else:
		dir='y'
	if script.texScrolls:
		script.texScrolls.append([Obj,script.CurrArea,Addr&0xFFFFFFF0,Num,Speed,dir,'normal',0])
	else:
		script.texScrolls = [[Obj,script.CurrArea,Addr&0xFFFFFFF0,Num,Speed,dir,'normal',0]]
	return Obj

def ConvertEditorTexScrollsAlt(script,Obj,PB):
	#Different format used in later versions of editor
	#Addr=0x8040+Byte2(X)<<16+Bparam1+2
	#Num=Bparam34
	#Speed=Byte2(Z)
	Addr=0x0E000000+((PB(Obj[1])-2)<<16)+(int(Obj[7],16)>>16) #x
	Num=int(Obj[7],16)&0xFFFF
	Speed=PB(Obj[3])
	dir = Addr&0xF
	if dir==0x8:
		dir='x'
	else:
		dir='y'
	if script.texScrolls:
		script.texScrolls.append([Obj,script.CurrArea,Addr&0xFFFFFFF0,Num,Speed,dir,'normal',0])
	else:
		script.texScrolls = [[Obj,script.CurrArea,Addr&0xFFFFFFF0,Num,Speed,dir,'normal',0]]
	return Obj

def FormatScrollObject(scroll,verts,obj,s,area):
	#not efficient at all, but number of scrolls is low and I'm lazy
	#vert = [seg ptr, rom ptr, num verts], sorted by seg ptrs
	if not verts:
		return None
	addr=scroll[2]
	closest=0
	offset=0
	#if verts are not in order, I can falsely assume the vert does not exist
	#becuase I see a gap and mistake it for the end of an area or something.
	verts.sort(key=lambda x: x[0])
	for v in verts:
		if addr>=v[0]:
			closest = v[0]
			offset = addr-v[0]
		if v[0]>addr:
			if offset>0xf0:
				offset=0xFF0
				Log.InvalidScroll(s.Currlevel,area,scroll)
			break
	else:
		Log.InvalidScroll(s.Currlevel,area,scroll)
		closest=addr
		offset=0xFF0
	global ScrollCount
	bparam = '%d'%ScrollCount
	ScrollCount+=1
	Bhvs = {
	'x':4,
	'y':5,
	'xPos':0,
	'yPos':1,
	'zPos':2,
	}
	Types = {
	'normal':0,
	'sine':1,
	'jumping':2,
	}
	#format I will use is bparam=addr,z=vert amount,x=spd,y=bhv,ry=type, rz=cycle
	# (Obj,script.CurrArea,Addr,Num,Speed,Bhvs[dir&0xF000],Types[dir&0xFFF],cycle)
	# PO=[id,x,y,z,rx,ry,rz,bparam,bhv,mask]
	obj[1]=scroll[4] #x
	obj[2]=Bhvs[scroll[-3]] #y
	obj[3]=scroll[3] #z
	obj[5]=Types[scroll[-2]] #ry
	obj[6]=scroll[-1] #rz
	obj[4]=int(offset/0x10) #rx
	obj[-3] = bparam
	s.ScrollArray.append(['VB_%s_%d_0x%x'%(GetlevelName(s.Currlevel),scroll[1],closest),int(offset/0x10)])
	return obj

def PlaceObject(rom,cmd,start,script):
	arg=cmd[2]
	A=script.GetArea()
	if not A:
		return start
	mask=arg[0]
	#remove disabled objects
	if mask==0:
		return start
	id=arg[1]
	#efficiency
	x=U2S(TcH(arg[2:4]))
	y=U2S(TcH(arg[4:6]))
	z=U2S(TcH(arg[6:8]))
	rx=U2S(TcH(arg[8:10]))
	ry=U2S(TcH(arg[10:12]))
	rz=U2S(TcH(arg[12:14]))
	bparam=hex(TcH(arg[14:18]))
	#check for MOP stuff first
	for a,b in MOPObjAddr.items():
		if (id,TcH(arg[18:22]))==a:
			bhv=' bhv'+b[0]
			PO=[id,x,y,z,rx,ry,rz,bparam,bhv,mask]
			break
	else:
		bhv=script.GetLabel("{:08x}".format(TcH(arg[18:22])))
		if bhv in "0x{:08x}".format(TcH(arg[18:22])):
			bhv = " Bhv_Custom_0x{:08x}".format(TcH(arg[18:22]))
			Log.UnkObject(script.Currlevel,script.CurrArea,bhv)
		PO=[id,x,y,z,rx,ry,rz,bparam,bhv,mask]
		if 'editor_Scroll_Texture' in bhv or 'RM_Scroll_Texture' in bhv:
			PO = ConvertTexScrolls(script,PO,rom)
	A.objects.append(PO)
	#for parsing later at the end
	script.objects.append([*PO,script.CurrArea,TcH(arg[18:22])])
	return start

def MacroObjects(rom,cmd,start,script):
	arg=cmd[2]
	macros = script.B2P(TcH(arg[2:6]))
	A=script.GetArea()
	A.macros = []
	x=0
	while(True):
		m = BitArray(rom[macros+x:macros+x+10])
		[yRot,Preset,X,Y,Z,Bp] = m.unpack("uint:7,uint:9,4*uint:16")
		if Preset<0x1F:
			break
		else:
			A.macros.append([yRot,Preset,X,Y,Z,Bp])
		x+=10
	return start

def PlaceMario(rom,cmd,start,script):
	#do nothing
	return start

def ConnectWarp(rom,cmd,start,script):
	A=script.GetArea()
	if not A:
		return start
	arg=cmd[2]
	W=(arg[0],arg[1],arg[2]+script.Aoffset,arg[3],arg[4])
	A.warps.append(W)
	return start

def PaintingWarp(rom,cmd,start,script):
	return start

def InstantWarp(rom,cmd,start,script):
	return start

def SetMarioDefault(rom,cmd,start,script):
	arg=cmd[2]
	script.mStart = [arg[0],U2S(TcH(arg[2:4])),U2S(TcH(arg[4:6])),U2S(TcH(arg[6:8])),U2S(TcH(arg[8:10]))]
	return start

def LoadCol(rom,cmd,start,script):
	arg=cmd[2]
	col=TcH(arg[2:6])
	A=script.GetArea()
	if not A:
		return start
	A.col=col
	return start

def LoadRoom(rom,cmd,start,script):
	return start

def SetDialog(rom,cmd,start,script):
	return start

def SetMusic(rom,cmd,start,script):
	A=script.GetArea()
	if A:
		arg=cmd[2]
		A.music=TcH(arg[3:4])
	return start

def SetMusic2(rom,cmd,start,script):
	A=script.GetArea()
	if A:
		arg=cmd[2]
		A.music=TcH(arg[1:2])
	return start

def SetTerrain(rom,cmd,start,script):
	A=script.GetArea()
	if A:
		arg=cmd[2]
		A.terrain=TcH(arg[1:2])
	return start

def ULC(rom,start):
	cmd = struct.unpack(">B",rom[start:start+1])[0]
	len = struct.unpack(">B",rom[start+1:start+2])[0]
	q=len-2
	args = struct.unpack(">%dB"%q,rom[start+2:start+len])
	return [cmd,len,args]

#iterates through script until a cmd is found that
#requires new action, then returns that cmd
def PLC(rom,start):
	(cmd,len,args) = ULC(rom,start)
	start+=len
	if cmd in jumps:
		return (cmd,len,args,start)
	return PLC(rom,start)

def WriteModel(rom,dls,s,name,Hname,id,tdir,skipTLUT):
	x=0
	ModelData=[]
	while(x<len(dls)):
		#check for bad ptr
		st=dls[x][0]
		first=TcH(rom[st:st+4])
		c=rom[st]
		if first==0x01010101 or not F3D.DecodeFmt.get(c):
			return
		try:
			(dl,verts,textures,amb,diff,ranges,starts,fog)=F3D.DecodeVDL(rom,dls[x],s,id,1,skipTLUT)
			if fog:
				f = name.relative_to(Path(sys.path[0])) / 'custom.model.inc.c'
				Log.LevelFog(str(f))
			ModelData.append([starts,dl,verts,textures,amb,diff,ranges,0])
		except:
			print("{} has a broken level DL and is being skipped".format(Num2LevelName.get(s.Currlevel)))
		x+=1
		s.verts.extend(verts) #for texture scrolls
	[refs,crcs] = F3D.ModelWrite(rom,ModelData,name,id,tdir,s.editor,s.Currlevel)
	modelH = name/'custom.model.inc.h'
	mh = open(modelH,'w')
	headgaurd="%s_HEADER_H"%(Hname)
	mh.write('#ifndef %s\n#define %s\n#include "types.h"\n'%(headgaurd,headgaurd))
	for r in refs:
		mh.write('extern '+r+';\n')
	mh.write("#endif")
	mh.close()
	del ModelData
	return dls

def ClosestIntinDict(num,dict):
	min=0xFFFFFFFFFFFFFF
	res = None
	for k,v in dict.items():
		if abs(k-num)<min:
			min=abs(k-num)
			res = v
	return res

def InsertBankLoads(s,f):
	banks = [s.banks[10],s.banks[15],s.banks[12],s.banks[13]]
	for i,b in enumerate(banks):
		if not i:
			if s.editor:
				d=skyboxesEditor
			else:
				d=skyboxesRM
		else:
			d=Groups
		if b and b[1]>b[0]:
			banks[i]=ClosestIntinDict(b[0],d)
			if not i:
				#custom skybox
				if b[0]>0x1220000:
					name = '_%s_skybox_mio0'%('SkyboxCustom%d'%b[0])
					load = "LOAD_MIO0(0xA,"+name+"SegmentRomStart,"+name+"SegmentRomEnd),\n"
				else:
					load = "LOAD_MIO0(0xA,"+banks[i]+"SegmentRomStart,"+banks[i]+"SegmentRomEnd),\n"
			else:
				load = "LOAD_MIO0(%d,"%banks[i][1]+banks[i][0]+"_mio0SegmentRomStart,"+banks[i][0]+"_mio0SegmentRomEnd),\n"
				load += "LOAD_RAW(%d,"%banks[i][2]+banks[i][0]+"_geoSegmentRomStart,"+banks[i][0]+"_geoSegmentRomEnd),\n"
			if f:
				f.write(load)
	return banks

def DetLevelSpecBank(s,f):
	level = None
	if s.banks[7]:
		#RM custom bank 7 check
		if s.banks[7][0]>0x1220000:
			return level
		level =ClosestIntinDict(s.banks[7][0],LevelSpecificBanks)
	return level

def LoadUnspecifiedModels(s,file,level):
	Grouplines = Group_Models.split("\n")
	for i,model in enumerate(s.models):
		if model:
			#Bank 0x14 is for menus, I will ignore it
			Seg = (model[0]>>24)
			if Seg==0x14:
				continue
			#Model Loads need to use groups because seg addresses are repeated so you can get the wrong ones
			#if you just use the map which has no distinction on which bank is loaded.
			addr = "{:08x}".format(model[0])
			if Seg==0x12:
				try:
					lab = GD.__dict__[level].get((i,'0x'+addr))
				except:
					lab=None
				if not lab:
					# print(addr,level,i)
					lab = s.GetLabel(addr)
				else:
					lab= lab[1]
			#actor groups, unlikely to exist outside existing group loads
			elif Seg==0xD or Seg==0xC:
				group = ClosestIntinDict(s.banks[Seg][0],Groups)[0][1:]
				lab = GD.__dict__[group].get((i,'0x'+addr))
				if not lab:
					lab = s.GetLabel(addr)
				else:
					lab= lab[1]
			#generally MOP
			elif Seg==0 or Seg==3 or Seg==0xF:
				for a,b in MOPModels.items():
					if (i,model[0])==a:
						#mops are loaded in entry script
						lab='MOP'
						break
				else:
					lab = s.GetLabel(addr)
			#group0, common0, common1 banks that have unique geo layouts
			else:
				lab = s.GetLabel(addr)
			if lab=='MOP':
				continue
			if '0x' in lab or not lab:
				comment = "// "
			else:
				comment = ""
			if LevelSpecificModels.get(level) and Seg==0x12:
				for l in LevelSpecificModels[level].split("\n"):
					if lab in l:
						break
				else:
					if model[1]=='geo':
						file.write(comment+"LOAD_MODEL_FROM_GEO(%d,%s),\n"%(i,lab))
					else:
						#Its just a guess but I think 4 will lead to the least issues
						file.write(comment+"LOAD_MODEL_FROM_DL(%d,%s,4),\n"%(i,lab))
			elif not (any([lab in l for l in Grouplines])):
				if model[1]=='geo':
					file.write(comment+"LOAD_MODEL_FROM_GEO(%d,%s),\n"%(i,lab))
				else:
					#Its just a guess but I think 4 will lead to the least issues
					file.write(comment+"LOAD_MODEL_FROM_DL(%d,%s,4),\n"%(i,lab))

def WriteLevelScript(name,Lnum,s,level,Anum,envfx):
	f = open(name,'w')
	f.write(scriptHeader)
	for a in Anum:
		f.write('#include "areas/%d/custom.model.inc.h"\n'%a)
	f.write('#include "levels/%s/header.h"\nextern u8 _%s_segment_ESegmentRomStart[]; \nextern u8 _%s_segment_ESegmentRomEnd[];\n'%(Lnum,Lnum,Lnum))
	#This is the ideal to match hacks, but currently the way the linker is
	#setup, level object data is in the same bank as level mesh so this cannot be done.
	LoadLevel = DetLevelSpecBank(s,f)
	if LoadLevel and LoadLevel!=Lnum:
		f.write('#include "levels/%s/header.h"\n'%LoadLevel)
	f.write('const LevelScript level_%s_entry[] = {\n'%Lnum)
	s.MakeDec('const LevelScript level_%s_entry[]'%Lnum)
	#entry stuff
	f.write("INIT_LEVEL(),\n")
	if LoadLevel:
		f.write("LOAD_MIO0(0x07, _"+LoadLevel+"_segment_7SegmentRomStart, _"+LoadLevel+"_segment_7SegmentRomEnd),\n")
		f.write("LOAD_RAW(0x1A, _"+LoadLevel+"SegmentRomStart, _"+LoadLevel+"SegmentRomEnd),\n")
	f.write("LOAD_RAW(0x0E, _"+Lnum+"_segment_ESegmentRomStart, _"+Lnum+"_segment_ESegmentRomEnd),\n")
	if envfx:
		f.write("LOAD_MIO0(        /*seg*/ 0x0B, _effect_mio0SegmentRomStart, _effect_mio0SegmentRomEnd),\n")
	#add in loaded banks
	banks = InsertBankLoads(s,f)
	f.write("ALLOC_LEVEL_POOL(),\nMARIO(/*model*/ MODEL_MARIO, /*behParam*/ 0x00000001, /*beh*/ bhvMario),\n")
	if LoadLevel:
		f.write(LevelSpecificModels[LoadLevel])
	#Load models that the level uses that are outside groups/level
	LoadUnspecifiedModels(s,f,LoadLevel)
	#add in jumps based on banks returned
	for b in banks:
		if type(b)==list and len(b)>2:
			f.write("JUMP_LINK("+b[3]+"),\n")
	#a bearable amount of cringe
	for a in Anum:
		id = Lnum+"_"+str(a)+"_"
		f.write('JUMP_LINK(local_area_%s),\n'%id)
	#end script
	f.write("FREE_LEVEL_POOL(),\n")
	f.write("MARIO_POS({},{},{},{},{}),\n".format(*s.mStart))
	f.write("CALL(/*arg*/ 0, /*func*/ lvl_init_or_update),\nCALL_LOOP(/*arg*/ 1, /*func*/ lvl_init_or_update),\nCLEAR_LEVEL(),\nSLEEP_BEFORE_EXIT(/*frames*/ 1),\nEXIT(),\n};\n")
	for a in Anum:
		id = Lnum+"_"+str(a)+"_"
		area=level[a]
		WriteArea(f,s,area,a,id)

def WriteArea(f,s,area,Anum,id):
	#begin area
	ascript = "const LevelScript local_area_%s[]"%id
	f.write(ascript+' = {\n')
	s.MakeDec(ascript)
	Gptr='Geo_'+id+hex(area.geo)
	f.write("AREA(%d,%s),\n"%(Anum,Gptr))
	f.write("TERRAIN(%s),\n"%("col_"+id+hex(area.col)))
	f.write("SET_BACKGROUND_MUSIC(0,%d),\n"%area.music)
	f.write("TERRAIN_TYPE(%d),\n"%(area.terrain))
	f.write("JUMP_LINK(local_objects_%s),\nJUMP_LINK(local_warps_%s),\n"%(id,id))
	if hasattr(area,'macros'):
		f.write("MACRO_OBJECTS('local_macro_objects_%s')"%id)
	f.write("END_AREA(),\nRETURN()\n};\n")
	asobj = 'const LevelScript local_objects_%s[]'%id
	f.write(asobj+' = {\n')
	s.MakeDec(asobj)
	#write objects
	for o in area.objects:
		if s.texScrolls:
			if 'Scroll_Texture' in o[-2]:
				for scroll in s.texScrolls:
					if scroll[0]==o and scroll[1]==Anum:
						o = FormatScrollObject(scroll,s.verts,o,s,Anum)
						break
		if o:
			if o[4]==255 and 'Scroll_Texture' in o[-2]:
				comment='// '
			else:
				comment=''
			f.write(comment+"OBJECT_WITH_ACTS({},{},{},{},{},{},{},{},{},{}),\n".format(*o))
	f.write("RETURN()\n};\n")
	aswarps = 'const LevelScript local_warps_%s[]'%id
	f.write(aswarps+' = {\n')
	s.MakeDec(aswarps)
	#write warps
	for w in area.warps:
		f.write("WARP_NODE({},{},{},{},{}),\n".format(*w))
	#write macro objects if they exist
	if hasattr(area,'macros'):
		asobj = 'const MacroObject local_macro_objects_%s[]'%id
		f.write(asobj+' = {\n')
		for m in area.macros:
			f.write("MACRO_OBJECT_WITH_BEH_PARAM({},{},{},{},{},{}),\n".format(MacroNames[m[1]],m[0],*m[2:]))
		f.write("MACRO_OBJECT_END(),\n};")
	f.write("RETURN()\n};\n")

def GrabOGDatH(q,rootdir,name):
	if name.startswith("ext_level"):
		dir = rootdir/'originals'/'bob'
	else:
		dir = rootdir/'originals'/name
	head = open(dir/'header.h','r')
	head = head.readlines()
	for l in head:
		if not l.startswith('extern'):
			continue
		q.write(l)
	return q

def GrabOGDatld(L,rootdir,name):
	dir = rootdir/'originals'/name
	ld = open(dir/'leveldata.c','r')
	ld = ld.readlines()
	grabbed = []
	for l in ld:
		if not l.startswith('#include "levels/%s/'%name):
			continue
		#mem bloat but makes up for mov tex being dumb
		# if ('/areas/' in l and '/model.inc.c' in l):
			# continue
		#for the specific case of levels without subfolders
		q = l.split('/')
		if len(q)>4:
			if ('areas' in q[2] and 'model.inc.c' in q[4]):
				continue
		#I want to include static objects in collision
		# if ('/areas/' in l and '/collision.inc.c' in l):
			# continue
		L.write(l)
		grabbed.append(l)
	return [L,grabbed]

def WriteVanillaLevel(rom,s,num,areas,rootdir,m64dir,AllWaterBoxes,Onlys,romname,m64s,seqNums,MusicExtend):
	WaterOnly = Onlys[0]
	ObjectOnly = Onlys[1]
	MusicOnly = Onlys[2]
	OnlySkip = any(Onlys)
	name=GetlevelName(num)
	level=Path(rootdir)/'levels'/("%s"%name)
	original = rootdir/'originals'/("%s"%name)
	shutil.copytree(original,level)
	#open original script
	script = level / 'script.c'
	scriptO = open(script,'r')
	Slines = scriptO.readlines()
	scriptO.close()
	script = open(script,'w')
	#go until an area is found
	x=0 #line pos
	restrict = ['OBJECT','WARP_NODE','JUMP_LINK']
	CheckRestrict = (lambda x: any([r in x for r in restrict]))
	macro=0
	for a in areas:
		j=0
		area=s.levels[num][a]
		#advanced past includes for first area
		if a==1:
			while(x<len(Slines)):
				if '"levels/%s/header.h"'%name in Slines[x]:
					x+=1
					break
				#scripts always start with some static data
				if 'static' in Slines[x]:
					break
				x+=1
		#write macro objects if they exist
		CheckMacro = (lambda x: 0)
		if hasattr(area,'macros'):
			CheckMacro = (lambda x: 'MACRO_OBJECTS(' in x )
			if not macro:
				hd = '#include "level_misc_macros.h"\n#include "macro_presets.h"\n'
				Slines.insert(x,(hd))
				x+=1
				macro=1
			asobj = 'static const MacroObject local_macro_objects_%s_%d[]'%(name,a)
			Slines.insert(x,(asobj+' = {\n'))
			x+=1
			for m in area.macros:
				Slines.insert(x,"MACRO_OBJECT_WITH_BEH_PARAM({},{},{},{},{},{}),\n".format(MacroNames[m[1]],m[0],*m[2:]))
				x+=1
			Slines.insert(x,"MACRO_OBJECT_END(),\n};\n")
			x+=1
	for a in areas:
		while(x<len(Slines)):
			if ' AREA(' in Slines[x]:
				x+=1
				break
			x+=1
		#remove other objects/warps
		while(j+x<len(Slines)):
			if CheckRestrict(Slines[j+x]) or CheckMacro(Slines[j+x]):
				Slines.pop(j+x)
				continue
			elif 'END_AREA()' in Slines[j+x]:
				j+=1
				break
			else:
				j+=1

		for o in area.objects:
			Slines.insert(x,"OBJECT_WITH_ACTS({},{},{},{},{},{},{},{},{},{}),\n".format(*o))
		for w in area.warps:
			Slines.insert(x,"WARP_NODE({},{},{},{},{}),\n".format(*w))
		if hasattr(area,'macros'):
			Slines.insert(x,"MACRO_OBJECTS(local_macro_objects_%s_%d),\n"%(name,a))
		x=j+x
		#area dir
		Arom = area.rom
		if area.music and not (ObjectOnly or WaterOnly):
			[m64,seqNum] = RipSequence(Arom,area.music,m64dir,num,a,romname,MusicExtend)
			if m64 not in m64s:
				m64s.append(m64)
				seqNums.append(seqNum)
		#write objects and warps for each area
	[script.write(l) for l in Slines]
	return [AllWaterBoxes,m64s,seqNums]

def WriteLevel(rom,s,num,areas,rootdir,m64dir,AllWaterBoxes,Onlys,romname,m64s,seqNums,MusicExtend,skipTLUT):
	#create level directory
	WaterOnly = Onlys[0]
	ObjectOnly = Onlys[1]
	MusicOnly = Onlys[2]
	OnlySkip = any(Onlys)
	name=GetlevelName(num)
	level=Path(rootdir)/'levels'/("%s"%name)
	if name.startswith("ext_level"):
		original = rootdir/'originals'/"bob"
	else:
		original = rootdir/'originals'/("%s"%name)
	shutil.copytree(original,level)
	Areasdir = level/"areas"
	Areasdir.mkdir(exist_ok=True)
	#create area directory for each area
	envfx = 0
	WriteLevelScript(level/"custom.script.c",name,s,s.levels[num],areas,envfx)
	for a in areas:
		#area dir
		adir = Areasdir/("%d"%a)
		adir.mkdir(exist_ok=True)
		area=s.levels[num][a]
		Arom = area.rom
		if area.music and not (ObjectOnly or WaterOnly):
			[m64,seqNum] = RipSequence(Arom,area.music,m64dir,num,a,romname,MusicExtend)
			if m64 not in m64s:
				m64s.append(m64)
				seqNums.append(seqNum)
		#get real bank 0x0e location
		s.RME(a,Arom)
		id = name+"_"+str(a)+"_"
		if s.banks[10] and s.banks[10][1]>s.banks[10][0] and s.banks[10][0]>0x1220000:
			CBG=1
			cskybox='%s_skybox_Index'%('SkyboxCustom%d'%(s.banks[10][0]))
		else:
			CBG=0
			cskybox=''
		(geo,dls,WB,vfx)=GW.GeoParse(Arom,area.geo,s,area.geo,id,cskybox,CBG,a)
		#deal with some areas having it vs others not
		if vfx:
			envfx = 1
		if not OnlySkip:
			GW.GeoWrite(geo,adir/"custom.geo.inc.c",id)
			for g in geo:
				s.MakeDec("const GeoLayout Geo_%s[]"%(id+hex(g[1])))
		if not OnlySkip:
			dls = WriteModel(Arom,dls,s,adir,"%s_%d"%(name.upper(),a),id,level,skipTLUT)
			if not dls:
				print("{} has no Display Lists, that is very bad".format(name))
			else:
				for d in dls:
					s.MakeDec("Gfx DL_%s[]"%(id+hex(d[1])))
		#write collision file
		if not OnlySkip:
			ColParse.ColWrite(adir/"custom.collision.inc.c",s,Arom,area.col,id)
		s.MakeDec('const Collision col_%s[]'%(id+hex(area.col)))
		#write mov tex file
		if not (ObjectOnly or MusicOnly):
			#WB = [types][array of type][box data]
			MovTex = adir / "movtextNew.inc.c"
			MovTex = open(MovTex,'w')
			Wrefs = []
			for k,Boxes in enumerate(WB):
				wref = []
				for j,box in enumerate(Boxes):
					#Now a box is an array of all the data
					#Movtex is just an s16 array, it uses macros but
					#they don't matter
					dat = repr(box).replace("[","{").replace("]","}")
					dat = "static Movtex %sMovtex_%d_%d[] = "%(id,j,k) + dat+";\n\n"
					MovTex.write(dat)
					wref.append("%sMovtex_%d_%d"%(id,j,k))
				Wrefs.append(wref)
			for j,Type in enumerate(Wrefs):
				MovTex.write("const struct MovtexQuadCollection %sMovtex_%d[] = {\n"%(id,j))
				for k,ref in enumerate(Type):
					MovTex.write("{%d,%s},\n"%(k,ref))
				MovTex.write("{-1, NULL},\n};\n")
				s.MakeDec("struct MovtexQuadCollection %sMovtex_%d[]"%(id,j))
				AllWaterBoxes.append(["%sMovtex_%d"%(id,j),num,a,j])
		print('finished area '+str(a)+ ' in level '+name)
	#now write level script
	if not (WaterOnly or MusicOnly):
		WriteLevelScript(level/"custom.script.c",name,s,s.levels[num],areas,envfx)
	s.MakeDec("const LevelScript level_%s_entry[]"%name)
	if not OnlySkip:
		#finally write header
		H=level/"header.h"
		q = open(H,'w')
		headgaurd="%s_HEADER_H"%(name.upper())
		q.write('#ifndef %s\n#define %s\n#include "types.h"\n#include "game/moving_texture.h"\n'%(headgaurd,headgaurd))
		for h in s.header:
			q.write('extern '+h+';\n')
		#now include externs from stuff in original level
		q = GrabOGDatH(q,rootdir,name)
		q.write("#endif")
		q.close()
		#append to geo.c, maybe the original works good always??
		G = level/"custom.geo.c"
		g = open(G,'w')
		g.write(geocHeader)
		g.write('#include "levels/%s/header.h"\n'%name)
		for i,a in enumerate(areas):
			geo = '#include "levels/%s/areas/%d/custom.geo.inc.c"\n'%(name,(i+1))
			g.write(geo) #add in some support for level specific objects somehow
		g.close
		#write leveldata.c
		LD = level/"custom.leveldata.c"
		ld = open(LD,'w')
		ld.write(ldHeader)
		Ftypes = ['custom.model.inc.c"\n','custom.collision.inc.c"\n']
		ld.write('#include "levels/%s/textureNew.inc.c"\n'%(name))
		for i,a in enumerate(areas):
			ld.write('#include "levels/%s/areas/%d/movtextNew.inc.c"\n'%(name,(i+1)))
			start = '#include "levels/%s/areas/%d/'%(name,(i+1))
			for Ft in Ftypes:
					ld.write(start+Ft)
		ld.close
	return [AllWaterBoxes,m64s,seqNums]

#Finds out what model is based on seg addr and loaded banks
def ProcessModel(rom,editor,s,modelID,model):
	Seg=model[0]>>24
	folder=None
	bank = s.banks[Seg]
	#I'm skipping seg 14 for now, which is menu geo stuff
	if Seg==0x14:
		return [None,None,None,None]
	#A custom bank will be one that is loaded well after
	#all other banks are. This is not guaranteed, but nominal bhv
	if Seg!=0:
		if bank[0]>0x1220000:
			if model[2]=='geo':
				label = "custom_geo_{:08x}".format(model[0])
			else:
				label = "custom_DL_{:08x}".format(model[0])
			folder = "custom_{:08x}".format(model[0])
			return ('custom_%x'%bank[0],Seg,label,folder)
		#These are in Seg C, D, F, 16, 17
		if Seg!=7 and Seg!=0x12 and Seg!=0xE:
			#catch group0/common0/1 f3d/geo loads. f3d loads happen most often in these
			if Seg==8 or Seg==0xF:
				group='common0'
			elif Seg==3 or Seg==0x16:
				group='common1'
			elif Seg==4 or Seg==0x17:
				group='group0'
			else:
				group = ClosestIntinDict(bank[0],Groups)[0][1:]
			label = GD.__dict__[group].get((modelID,"0x{:08x}".format(model[0])))
			if label:
				folder = label[2]
				label=label[1]
		#These are all in bank 7 with geo layouts in bank 12. Bank 0xE is used for vanilla levels
		else:
			#if bank 19 doesn't exist, its a vanilla level and segE
			if not s.banks[0x19]:
				md=model[0]+0x04000000
			else:
				md=model[0]
			group = ClosestIntinDict(s.banks[7][0],LevelSpecificBanks)
			label = GD.__dict__[group].get((modelID,"0x{:08x}".format(md)))
			if label:
				folder = label[2]
				label=label[1]
	else:
		#check for mop first before giving it null status
		for a,b in MOPModels.items():
			if (modelID,model[0])==a:
				label=b
				group='MOP'
				folder=b
				break
		else:
			if model[2]=='geo':
				label = "Null_geo_{:08x}".format(model[0])
			else:
				label = "Null_DL_{:08x}".format(model[0])
			group='Null'
			folder='Null_{:08x}'.format(model[0])
		#attempt to guess rom address based on generic ram map. Might work for RM, unlikely to for editor
	#Something extra added to existing bank. Its a good idea to check for MOP here aswell
	#some part of MOP is inserted into seg3 while others are in 0xF and some just loaded directly to ram
	#like a caveman would.
	if not label:
		for a,b in MOPModels.items():
			if (modelID,model[0])==a:
				label=b
				folder=b
				group='MOP'
				break
		else:
			if model[2]=='geo':
				label = "unk_geo_{:08x}".format(model[0])
			else:
				label = "unk_DL_{:08x}".format(model[0])
			folder = "unk_{}_{:08x}".format(Num2LevelName.get(s.Currlevel),model[0])
			group = 'unk'
	return (group,Seg,label,folder)

#process all the script class objects from all exported levels to find specific data
def ProcessScripts(rom,editor,Scripts):
	#key=banknum, value = list of start/end locations
	Banks = {}
	#key=group name, values = [seg num,label,type,rom addr,seg addr,ID,folder,script]
	Models = {}
	#key=bhv, values = [ram addr, rom addr, models used with,script]
	Objects = {}
	for s in Scripts:
		#banks
		for k,B in enumerate(s.banks):
			if B:
				#throw out garbage editor fake loads
				if B[1]<B[0]:
					continue
				dupe = Banks.get(k)
				#check for duplicate which should be the case often
				if dupe and B not in dupe:
					Banks[k].append(B)
				elif not dupe:
					Banks[k] = [B]
		#models
		#refs of vals to IDs for this script alone so I can view with Objects dict
		IDs = {0:[None,None,None,None,None,None,None]}
		for k,M in enumerate(s.models):
			if M:
				[group,seg,l,f] = ProcessModel(rom,editor,s,k,M)
				if group==None:
					continue
				dupe = Models.get(group)
				val = [seg,l,M[1],M[3],M[0],k,f,M[4]]
				#check for duplicate which should be the case often
				if dupe and val not in dupe:
					Models[group].append(val)
				else:
					Models[group] = [val]
				IDs[k] = val[:7]
		for obj in s.objects:
			#modelid,x,y,z,rx,ry,rz,bparam,bhv label,mask,area,bhv hex
			if obj[8] in Objects.keys():
				if IDs.get(obj[0]) and IDs[obj[0]] not in Objects[obj[8]][2] and obj[0]!=0:
					Objects[obj[8]][2].append(IDs[obj[0]])
			else:
				#somehow I can not have the model loaded?? aka garbage level scripts
				try:
					Objects[obj[8]] = [obj[-1],s.B2P(obj[-1]),[IDs[obj[0]]],s]
				except:
					pass
	return [Banks,Models,Objects]

#dictionary of actions to take based on script cmds
jumps = {
    0:LoadRawJumpPush,
    1:LoadRawJump,
    2:Exit,
    5:JumpRaw,
    6:JumpPush,
    7:Pop,
    11:CondPop,
    12:CondJump,
    0x13:SetLevel,
    0x16:LoadAsm,
    0x17:LoadData,
    0x18:LoadMio0,
    0x1a:LoadMio0Tex,
    0x1f:StartArea,
    0x20:EndArea,
    0x21:LoadPolyF3d,
    0x22:LoadPolyGeo,
    0x24:PlaceObject,
    0x25:PlaceMario,
    0x26:ConnectWarp,
    0x27:PaintingWarp,
    0x28:InstantWarp,
    0x2b:SetMarioDefault,
    0x2e:LoadCol,
    0x2f:LoadRoom,
    0x30:SetDialog,
    0x31:SetTerrain,
    0x36:SetMusic,
    0x37:SetMusic2,
	0x39:MacroObjects
}

def RipNonLevelSeq(rom,m64s,seqNums,rootdir,MusicExtend,romname):
	m64dir = rootdir/'sound'/"sequences"/"us"
	os.makedirs(m64dir,exist_ok=True)
	NonLevels=[1,2,11,13,14,15,16,18,20,21,22,23,27,28,29,30,31,32,33]
	for i in NonLevels:
		if i not in seqNums:
			[m64,seqNum] = RipSequence(rom,i,m64dir,0,0,romname,MusicExtend)
			m64s.append(m64)
			seqNums.append(seqNum)

def RipSequence(rom,seqNum,m64Dir,Lnum,Anum,romname,MusicExtend):
	#audio_dma_copy_immediate loads gSeqFileHeader in audio_init at 0x80319768
	#the line of asm is at 0xD4768 which sets the arg to this
	UPW = (lambda x,y: struct.unpack(">L",x[y:y+4])[0])
	gSeqFileHeader=(UPW(rom,0xD4768)&0xFFFF)<<16 #this is LUI asm cmd
	gSeqFileHeader+=(UPW(rom,0xD4770)&0xFFFF) #this is an addiu asm cmd
	#format is tbl,m64s[]
	#tbl format is [len,offset][]
	gSeqFileOffset = gSeqFileHeader+seqNum*8+4
	len=UPW(rom,gSeqFileOffset+4)
	offset=UPW(rom,gSeqFileOffset)
	m64 = rom[gSeqFileHeader+offset:gSeqFileHeader+offset+len]
	m64File = m64Dir/("{1:02X}_Seq_{0}_custom.m64".format(romname,seqNum+MusicExtend))
	m64Name = "{1:02X}_Seq_{0}_custom".format(romname,seqNum+MusicExtend)
	f = open(m64File,'wb')
	f.write(m64)
	f.close()
	return [m64Name,seqNum+MusicExtend]

def CreateSeqJSON(rom,m64s,rootdir,MusicExtend):
	originals = rootdir/"originals"/"sequences.json"
	m64Dir = rootdir/'sound'
	m64s.sort(key=(lambda x: x[1]))
	origJSON = open(originals,'r')
	origJSON = origJSON.readlines()
	#This is the location of the Bank to Sequence table.
	seqMagic = 0x7f0000
	#format is u8 len banks (always 1), u8 bank. Maintain the comment/bank 0 data of the original sequences.json
	UPB = (lambda x,y: struct.unpack(">B",x[y:y+1])[0])
	UPH = (lambda x,y: struct.unpack(">h",x[y:y+2])[0])
	seqJSON = m64Dir/"sequences.json"
	seqJSON = open(seqJSON,'w')
	last = 0
	for j,m64 in enumerate(m64s):
		bank = UPH(rom,seqMagic+(m64[1]-MusicExtend)*2)
		bank = UPB(rom,seqMagic+bank+1)
		if bank>37:
			print("sound bank error, try exporting with different rom type (e.g. editor=0)\nseq json may not work properly")
			break
		if MusicExtend:
			seqJSON.write("\t\"{}\": [\"{}\"],\n".format(m64[0],SoundBanks[bank]))
			continue
		#fill in missing sequences
		for i in range(last,m64[1]+2,1):
			if i>36:
				break
			if i==36:
				seqJSON.write(origJSON[i][:-1]+',\n')
				break
			seqJSON.write(origJSON[i])
		comma = ","*(j<(len(m64s)-1)) #last index can't have comma or json doesn't parse
		seqJSON.write("\t\"{}\": [\"{}\"]{}\n".format(m64[0],SoundBanks[bank],comma))
		if m64[1]<0x23:
			og = origJSON[m64[1]+2]
			og = og.split(":")[0] + ": null,\n"
			seqJSON.write(og)
		last = m64[1]+3
	seqJSON.write("}")

def RipInstBanks(rom,rootdir):
	sampledir = rootdir/'sound'/'samples'
	instsdir = rootdir/'sound'/'sound_banks'
	os.makedirs(sampledir,exist_ok=True)
	os.makedirs(instsdir,exist_ok=True)
	#<.z64 rom> <ctl offset> <ctl size> <tbl offset> <tbl size> (<samples outdir> <sound bank outdir> | --only-samples file:index ...)
	try:
		d_s.main(rom,0x57B720,97856,0x593560,2216704,sampledir,instsdir)
	except:
		print('sound bank exporting went wrong somewhere.')

def AppendAreas(entry,script,Append):
	for rom,offset,editor in Append:
		script.Aoffset = offset
		script.editor = editor
		Arom=open(rom,'rb')
		Arom = Arom.read()
		#get all level data from script
		while(True):
			#parse script until reaching special
			q=PLC(Arom,entry)
			#execute special cmd
			entry = jumps[q[0]](Arom,q,q[3],script)
			#check for end, then loop
			if not entry:
				break
	return script

def ExportLevel(rom,level,editor,Append,AllWaterBoxes,Onlys,romname,m64s,seqNums,MusicExtend,lvldefs,skipTLUT):
	#choose level
	s = Script(level)
	global Seg15Location
	entry = Seg15Location
	s = AppendAreas(entry,s,Append)
	s.Aoffset = 0
	s.editor = editor
	rootdir = Path(sys.path[0])
	m64dir = rootdir/'sound'/"sequences"/"us"
	os.makedirs(m64dir,exist_ok=True)
	#get all level data from script
	x=0
	while(True):
		#parse script until reaching special
		q=PLC(rom,entry)
		#execute special cmd
		entry = jumps[q[0]](rom,q,q[3],s)
		x+=1
		#check for end, then loop
		if not entry:
			break
		#you've hit a inf loop, usually in end screens with no level
		if x>10000:
			return s
	#this tool isn't for exporting vanilla levels
	#so I export only objects for these levels
	if not s.banks[0x19]:
		print(f"Level {GetlevelName(level)} is unmodified!")
		WriteVanillaLevel(rom,s,level,s.GetNumAreas(level),rootdir,m64dir,AllWaterBoxes,[Onlys[0],1,Onlys[0]],romname,m64s,seqNums,MusicExtend)
		return s
	lvldefs.write("DEFINE_LEVEL(%s,%s)\n"%(GetlevelName(level),"LEVEL_"+GetlevelName(level).upper()))
	#now do level
	[AllWaterBoxes,m64s,seqNums] = WriteLevel(rom,s,level,s.GetNumAreas(level),rootdir,m64dir,AllWaterBoxes,Onlys,romname,m64s,seqNums,MusicExtend,skipTLUT)
	return s

class Actor():
	def __init__(self,aDir,actors):
		self.folders ={}
		self.dir = aDir
		rdir = Path(sys.path[0])
		self.ExpType=actors
		# self.CHKSM = open(rdir/'ActorCHKSM.py','w') This was written for checksum collection purposes
	def EvalModel(self,model,group):
		folder = self.folders.get(model[6])
		if folder:
			for v in folder:
				if model[3] in v:
					break
			else:
				self.folders[model[6]].append([*model[0:5],model[7],group])
		else:
			self.folders[model[6]] = [[*model[0:5],model[7],group]]
	def MakeFolders(self,rom):
		#key is folder name, values = [seg num,label,type,rom addr, seg addr,ID,script,groupname]
		for k,val in self.folders.items():
			fold = self.dir / k
			os.makedirs(fold,exist_ok=True)
			if not (k=='Null' or val[0][6]=='MOP'):
				self.ParseModels(val,k,rom,fold)
			else:
				try:
					self.ParseModels(val,k,rom,fold)
				except:
					print('Model {} was in bank 0 and its rom address could not be detected properly'.format(k))
		self.ExportPowerMeter(rom,val[0][5])
	def ParseModels(self,val,k,rom,fold):
		fgeo = fold/'custom.geo.inc.c'
		fgeo = open(fgeo,'w')
		geos = []
		dls = []
		ids = []
		for v in val:
			#edit model to have ROM address. MOP seg 0 is mapped with 0x5F0000 = 0x7D0000
			if v[2]=='geo':
				try:
					[geo,dl] = GW.GeoActParse(rom,v)
					geos.extend(geo)
					dls.append(dl)
					ids.append(v[1]+'_')
				except:
					print(k + " is broken, will not export")
			#load via f3d
			else:
				dls.append([[v[3],v[4]]])
				ids.append(v[1]+'_')
		if geos:
			GW.GeoActWrite(geos,fgeo)
			del geos
			del fgeo
		#turn editor off for script object so optimization
		#doesn't happen
		v[5].editor=0
		try:
			self.WriteActorModel(rom,dls,v[5],k.split("/")[0]+'_'+k.split("/")[-1]+'_model',ids,fold,v[-1],k)
			print('actor {} exported'.format(k))
		except:
			pass
	def WriteActorModel(self,rom,dlss,s,Hname,ids,dir,groupname,foldname):
		x=0
		ModelData=[]
		for dls,id in zip(dlss,ids):
			x=0
			while(x<len(dls)):
				#check for bad ptr
				st=dls[x][0]
				first=TcH(rom[st:st+4])
				c=rom[st]
				if first==0x01010101 or not F3D.DecodeFmt.get(c):
					return
				try:
					(dl,verts,textures,amb,diff,ranges,starts, fog) = F3D.DecodeVDL(rom,dls[x],s,id,0, False)
					ModelData.append([starts,dl,verts,textures,amb,diff,ranges,id])
				except:
					print(f"actor {Hname} had a broken DL and the DL cannot be exported")
				x+=1
		#change tdir to level dir
		if groupname in Num2LevelName.values():
			tdir = Path(sys.path[0])/'levels'/groupname
			os.makedirs(tdir,exist_ok=True)
			[refs,crcs] = F3D.ModelWrite(rom,ModelData,dir,ids[0],tdir,s.editor,s.Currlevel)
		else:
			[refs,crcs] = F3D.ModelWrite(rom,ModelData,dir,ids[0],dir,s.editor,s.Currlevel)
		# self.CHKSM.write("{} = {}\n".format(ids[0],crcs)) This was written for checksum collection purposes
		new=self.CompareChecksums(crcs,ids[0],foldname)
		if not new and self.ExpType=='new':
			#delete entire directory. A try here is real bad code but for
			#some reason it keeps failing on just one model and idk why
			try:
				shutil.rmtree(dir)
			except:
				pass
			return
		modelH = dir/'custom.model.inc.h'
		mh = open(modelH,'w')
		headgaurd="%s_HEADER_H"%(Hname)
		mh.write('#ifndef %s\n#define %s\n#include "types.h"\n'%(headgaurd,headgaurd))
		for r in refs:
			mh.write('extern '+r+';\n')
		mh.write("#endif")
		mh.close()
		#free memory because actors take a lot
		del ModelData,refs,mh
		gc.collect()
	def CompareChecksums(self,crcs,id,fold):
		if id not in ActorCHKSM.__dict__.keys():
			Log.UnkModel(id,fold)
			return 1
		else:
			cksm = ActorCHKSM.__dict__.get(id)
			for c in crcs:
				if c not in cksm:
					Log.UnkModel(id,fold)
					return 1
		return 0
	#Hardcode power meter export. Only exporting textures
	def ExportPowerMeter(self,rom,script):
		dir = self.dir / 'power_meter'
		dir.mkdir(exist_ok=True)
		nums = ['full','seven_segments','six_segments','five_segments','four_segments','three_segments','two_segments','one_segment']
		for i in range(8):
			base = 'power_meter_%s.rgba16'%(nums[i])
			png = BinPNG.MakeImage(str(dir/base))
			loc = script.B2P(0x03000000+0x253E0+i*0x800)
			bin = rom[loc:loc+0x800]
			BinPNG.RGBA16(32,32,bin,png)
		png = BinPNG.MakeImage(str(dir/'power_meter_left_side.rgba16'))
		loc = script.B2P(0x03000000+0x233E0)
		bin = rom[loc:loc+0x1000]
		BinPNG.RGBA16(32,64,bin,png)
		png = BinPNG.MakeImage(str(dir/'power_meter_right_side.rgba16'))
		loc = script.B2P(0x03000000+0x243E0)
		bin = rom[loc:loc+0x1000]
		BinPNG.RGBA16(32,64,bin,png)

def ExportActors(actors,rom,Models,aDir):
	#Models is key=group name, values = [seg num,label,type,rom addr, seg addr,ID,folder,script]
	Actors = Actor(aDir,actors)
	levels = list(Num2Name.values())
	#every model seen
	if actors=='all':
		for group,models in Models.items():
			if group in levels:
				pass
			for m in models:
				Actors.EvalModel(m,group)
		return Actors.MakeFolders(rom)
	#export every model, but upon checksum comparison don't write unless its new
	elif actors=='new':
		for group,models in Models.items():
			if group in levels:
				pass
			for m in models:
				Actors.EvalModel(m,group)
		return Actors.MakeFolders(rom)
	#only models with a known modelID geo addr combo
	elif actors=='old':
		for group,models in Models.items():
			if group in levels:
				pass
			for m in models:
				if 'custom' not in m[1] and 'unk' not in m[1]:
					Actors.EvalModel(m,group)
		return Actors.MakeFolders(rom)
	elif actors=='all_new':
		for group,models in Models.items():
			if group in levels:
				pass
			for m in models:
				if 'custom' in m[1] or 'unk' in m[1] or 'Null' in m[1]:
					Actors.EvalModel(m,group)
		return Actors.MakeFolders(rom)
	#if its not one of the above phrases, its the name of a group
	elif type(actors)==str:
		try:
			models = Models[actors]
		except:
			print("group {} doesn't exist.\nHere are the avaiable groups\n{}".format(actors,list(Models.keys())))
			return
		if actors in levels:
			pass
		for m in models:
			if m[1]:
				Actors.EvalModel(m,actors)
		return Actors.MakeFolders(rom)
	#only option left is a list of groups
	for a in actors:
		try:
			models = Models[a]
		except:
			continue
		if a in levels:
			pass
		for m in models:
			if m[1]:
				Actors.EvalModel(m,a)
	return Actors.MakeFolders(rom)

def ExportObjects(reg,Objects,rom,ass,rootdir,editor):
	#key=bhv, values = [rom addr, ram addr, models used with,script]
	bdir = rootdir / 'data'
	os.makedirs(bdir,exist_ok=True)
	bdata = bdir / 'custom.behavior_data.inc.h'
	bdata = open(bdata,'w')
	bdata.write(Bdatahead)
	collisions = []
	functions = []
	f=0 #stubbed
	if type(reg)==list:
		for bhv,o in Objects.items():
			r = [re.search(a,bhv) for a in reg]
			if any(r):
				[col,funcs] = ExportBhv(o,bdata,bhv,0,f,editor,rom)
				if col:
					collisions.append([col,o,bhv,new])
				if funcs:
					functions.extend(funcs)
	else:
		if reg=='all':
			# f = open('BehComp.py','w') #used to generate data for BehComp
			for bhv,o in Objects.items():
				[col,funcs,new] = ExportBhv(o,bdata,bhv,0,f,editor,rom)
				if col:
					collisions.append([col,o,bhv,new])
				if funcs:
					functions.extend(funcs)
		elif reg=='new':
			#Export all, but then do a comparison on whether or not to write
			for bhv,o in Objects.items():
				[col,funcs,new] = ExportBhv(o,bdata,bhv,1,f,editor,rom)
				if col:
					collisions.append([col,o,bhv,new])
				if funcs:
					functions.extend(funcs)
		else:
			for bhv,o in Objects.items():
				r = re.search(reg,bhv)
				if r:
					[col,funcs,new] = ExportBhv(o,bdata,bhv,0,f,editor,rom)
					if col:
						collisions.append([col,o,bhv,new])
					if funcs:
						functions.extend(funcs)
	# C = open('ColComp.py','w') #used to generate data for checkCol
	C = 0
	for col in collisions:
		#Check for collision with multiple entries
		if type(col[0])==list:
			for c in col[0]:
				c=[c,col[1],col[2],0]
				ExportActorCol(c,reg,rom,C,ass)
		else:
			ExportActorCol(col,reg,rom,C,ass)
	if functions:
		ExportFunctions(functions,rom,bdir)

def ExportActorCol(col,reg,rom,C,ass):
	#sometimes they have no model
	if col[1][2]:
		cname = col[1][2][0][6]
		cid = col[1][2][0][1]
		if not cname or not cid:
			cname = 'Unk_Collision_{}'.format(col[0])
			cid = 'Unk_Collision_{}'.format(col[0])
		cdir = ass/cname
	else:
		cname = 'Unk_Collision_{}'.format(col[0])
		cid = 'Unk_Collision_{}'.format(col[0])
		cdir = ass/cname
	os.makedirs(cdir,exist_ok=True)
	if 'custom' in cid or 'Unk' in cid:
		Log.UnkCollision(cid,cname,col[2])
	cdir = cdir / 'custom.collision.inc.c'
	id = cid+"_"
	try:
		ColD = ColParse.ColWriteActor(cdir,col[1][3],rom,int(col[0]),id)
		checkCol(ColD,id,cdir,col[2],reg,cname)
		# C.write("{} = {}\n".format(id,ColD)) #used to generate data for checkCol
		print("actor {}'s collision exported".format(cname))
	except:
		print("actor {}'s collision could not be exported. Invalid address".format(cname))

def checkCol(ColD,id,cdir,Bhv,reg,cname):
	if id not in ColComp.__dict__.keys():
		return 1
	else:
		DictDat = ColComp.__dict__.get(id)
		if not DictDat == ColD:
			Log.UnkCollision(id,cname,Bhv)
			return 1
		else:
			c = cdir/'custom.collision.inc.c'
			if os.path.exists(c) and reg=='new':
				os.remove(c)
			return 0

def ExportFunctions(functions,rom,Bdir):
	md=Cs(CS_ARCH_MIPS,CS_MODE_MIPS64+CS_MODE_BIG_ENDIAN)
	# md.detail = True
	jumps=['jr','j']
	stop=0x1000
	FuncFile = Bdir/'Custom_Asm.s'
	FuncFile = open(FuncFile,'w')
	FuncFile.write("#This file is provided only as a reference for manually recoding functions.\n\n")
	starts=[]
	#[addr (str),Bhv name,Function name,script]
	for f in functions:
		script=f[3]
		start=V2P(script,int(f[0])&0X7FFFFFFF)
		if start in starts:
			continue
		else:
			starts.append(start)
		code=rom[start:start+0x1000]
		FuncFile.write("#This function is called from Behavior {}\n#It has virtual address 0x{:X} and rom address 0x{:X}\n{}:\n".format(f[1],int(f[0]),start,f[2]))
		for k,i in enumerate(md.disasm(code,0)):
			#attempt to get label
			if i.mnemonic=='jal':
				addr = "{:08x}".format(int(i.op_str,16)+0x80000000)
				op = script.GetLabel(addr)
			else:
				op=i.op_str
			FuncFile.write("\t%s\t%s\n" %(i.mnemonic, op))
			if any([j == i.mnemonic for j in jumps]):
				stop=k
				AddFunction(functions,script,i.op_str,f)
			if k>stop:
				break

#op is a number, but its read physically, so it drops the MSB
def V2P(script,opR):
	region=[0,0,0]
	for asm in script.asm:
		start=asm[0]&0x7FFFFFFF
		if opR>start and start>(region[0]&0x7FFFFFFF):
			region=asm
	return opR-(region[0]&0x7FFFFFFF)+region[1]

def AddFunction(functions,script,op,f):
	if '0x' not in op:
		return functions
	opR=int(op,16)
	opR=V2P(script,opR)
	start=opR+0x80000000
	Fname = 'Func_Custom_{}'.format(hex(start))
	functions.append([str(start),f[1],Fname,script])
	return functions

#f exists if I need to recreate a new comparison file of behaviors
def ExportBhv(o,bdata,bhv,check,f,editor,rom):
	Bhvs=[[o[1],o[-1],bhv]]
	#Behaviors are scripts and can jump around. This keeps track of all jumps and gotos
	funcs=[]
	cols=[]
	while(Bhvs):
		bhv=Bhvs[0][2]
		Bhv = BP.Behavior(*Bhvs[0],o[2])
		Bhvs.pop(0)
		#there is absolutely no reason to believe bhvs cannot be stubbed or just destroyed by random data
		#in a romhack and then never touched.
		try:
			[BhvScript,col,func,Bhvs]= Bhv.Parse(rom,Bhvs)
			#Do some hardcoded col pointers for things that are abstracted
			#Such as platforms on tracks
			col=FindHardcodedCols(rom,col,bhv,editor)
			if col:
				cols.append(col)
			funcs.extend(func)
			#Compare the output behavior here, and write it to the log
			new = CompareBeh(BhvScript,bhv)
			# f.write("{} = {}\n".format(bhv,BhvScript)) #used to generate data for CompareBeh
			bdata.write("const BehaviorScript{}[] = {{\n".format(bhv))
			[bdata.write(s+',\n') for s in BhvScript]
			bdata.write('};\n\n')
			print("{} exported".format(bhv))
		except:
			print("Behavior {} failed to export".format(bhv))
			col=[]
			new=0
	return [cols,funcs,new]

def CompareBeh(BhvScript,bhv):
	if bhv not in BehComp.__dict__.keys():
		return 1
	else:
		BhvScr = ActorCHKSM.__dict__.get(bhv)
		if not BhvScr == BhvScript:
			Log.NewObject(bhv)
			return 1
		else:
			return 0

def FindHardcodedCols(rom,col,bhv,editor):
	if bhv==' bhvPlatformOnTrack' and not col:
		#I despise romhacks
		if editor:
			return 0x07003780
		col=[]
		for k,v in TrackHardCodedCols.items():
			Dat = UPA(rom,v,'>L',4)[0]
			col.append(Dat)
	return col

def FindCustomSkyboxse(rom,Banks,SB):
	custom = {}
	if not Banks:
		return custom
	for j,B in enumerate(Banks[0xA]):
		if B[0]>0x1220000:
			custom[B[0]] = '_SkyboxCustom%d'%B[0]
	#make some skybox rules for the linker so it can find these
	f = open(SB / 'Skybox_Rules.ld','w')
	for v in custom.values():
		f.write('   MIO0_SEG({}, 0x0A000000)\n'.format(v[1:]+"_skybox"))
	return custom

def ExportTextures(rom,editor,rootdir,Banks,inherit):
	s=Script(9)
	Textures = rootdir/"textures"
	if os.path.isdir(Textures) and not inherit:
		shutil.rmtree(Textures)
	Textures.mkdir(exist_ok=True)
	#There are several different banks of textures, all are in bank 0xA or 0xB or 0x2
	#Editor and RM have different bank load locations, this is because editor didn't follow alignment
	#Seg2 func accounts for this by detecting the asm load, other banks will have to use different dicts
	#Skyboxes are first. Each skybox has its own bank. This alg will export each skybox tile, then merge
	#them into one skybox and delete them all. Its pretty slow.
	SB = Textures/'skyboxes'
	SB.mkdir(exist_ok=True)
	if editor:
		skyboxes=skyboxesEditor
	else:
		skyboxes = skyboxesRM
	#Check for custom skyboxes using Banks
	skyboxes = {**FindCustomSkyboxse(rom,Banks,SB),**skyboxes}
	p = mp.Pool(mp.cpu_count())
	for k,v in skyboxes.items():
		imgs = []
		name = v.split('_')[1]
		if name=='cloud':
			name='cloud_floor'
		imgs = p.starmap(ExportSkyTiles,[(SB,rom,v,k,i) for i in range(0x40)])
		# for i in range(0x40):
			# namet = v.split('_')[1]+str(i)
			# box = BinPNG.MakeImage(str(SB / namet))
			# bin = rom[k+i*0x800:k+0x800+i*0x800]
			# BinPNG.RGBA16(32,32,bin,box)
			# imgs.append(box)
		FullBox = BinPNG.InitSkybox(str(SB / name))
		for j,tile in enumerate(imgs):
			x=(j*31)%248
			y=int((j*31)/248)*31
			BinPNG.TileSkybox(FullBox,x,y,tile)
		FullBox.save(str(SB / (name+'.png')))
		[os.remove(Path(img)) for img in imgs]
		print('skybox %s done'%name)
	ExportSeg2(rom,Textures,s)
	print('skyboxes done')

def ExportSkyTiles(SB,rom,v,k,i):
	namet = v.split('_')[1]+str(i)
	box = BinPNG.MakeImage(str(SB / namet))
	bin = rom[k+i*0x800:k+0x800+i*0x800]
	BinPNG.RGBA16(32,32,bin,box)
	box.close()
	return str(SB / (namet+'.png'))

#segment 2
def ExportSeg2(rom,Textures,s):
	Seg2 = Textures/'segment2'
	Seg2.mkdir(exist_ok=True)
	#seg2 textures have a few sections. First is 16x16 HUD glyphs. 0x200 each
	nameOff=0
	global Seg2Location
	for tex in range(0,0x4A00,0x200):
		if tex in Seg2Glpyhs:
			nameOff+=Seg2Glpyhs[tex]
		gname = 'segment2.{:05X}.rgba16'.format(tex+nameOff)
		glyph = BinPNG.MakeImage(str(Seg2 / gname))
		loc = s.B2P(Seg2Location +tex)
		bin = rom[loc:loc+0x200]
		BinPNG.RGBA16(16,16,bin,glyph)
	#cam glyphs are separate
	nameOff=0xb50
	for tex in range(0x7000,0x7600,0x200):
		gname = 'segment2.{:05X}.rgba16'.format(tex+nameOff)
		glyph = BinPNG.MakeImage(str(Seg2 / gname))
		loc = s.B2P(Seg2Location+tex)
		bin = rom[loc:loc+0x200]
		BinPNG.RGBA16(16,16,bin,glyph)
	#cam up/down are 8x8
	for tex in range(0x7600,0x7700,0x80):
		gname = 'segment2.{:05X}.rgba16'.format(tex+nameOff)
		glyph = BinPNG.MakeImage(str(Seg2 / gname))
		loc = s.B2P(Seg2Location+tex)
		bin = rom[loc:loc+0x80]
		BinPNG.RGBA16(8,8,bin,glyph)
	#Now exporting dialog chars. They are 16x8 IA4. 0x40 in length each.
	for char in range(0x5900,0x7000,0x40):
		gname = 'font_graphics.{:05X}.ia4'.format(char)
		glyph = BinPNG.MakeImage(str(Seg2 / gname))
		loc = s.B2P(Seg2Location+char)
		bin = rom[loc:loc+0x40]
		BinPNG.IA(16,8,4,bin,glyph)
	#now credits font. Its 8x8 rgba16, 0x80 length each
	nameOff=0x6200-0x4A00
	for char in range(0x4A00,0x5900,0x80):
		#the names are offset from actual loc
		gname = 'segment2.{:05X}.rgba16'.format(char+nameOff)
		glyph = BinPNG.MakeImage(str(Seg2 / gname))
		loc = s.B2P(Seg2Location+char)
		bin = rom[loc:loc+0x80]
		BinPNG.RGBA16(8,8,bin,glyph)
	#shadows. 16x16 IA8. 0x100 len
	names = ['shadow_quarter_circle','shadow_quarter_square']
	for char in range(2):
		gname = '{}.ia4'.format(names[char])
		glyph = BinPNG.MakeImage(str(Seg2 / gname))
		loc = s.B2P(Seg2Location+char*0x100+0x120b8)
		bin = rom[loc:loc+0x100]
		BinPNG.IA(16,16,8,bin,glyph)
	#warp transitions. 32x64 or 64x64. I will grab data from arr for these
	for warp in Seg2WarpTransDat:
		gname = 'segment2.{}.ia4'.format(warp[1])
		glyph = BinPNG.MakeImage(str(Seg2 / gname))
		loc = s.B2P(Seg2Location+warp[0])
		bin = rom[loc:loc+warp[3]]
		BinPNG.IA(*warp[2],8,bin,glyph)
	#last in seg2 is water boxes. These are all rgba16 32x32 except mist which is IA16
	nameOff=0x11c58-0x14AB8
	for tex in range(5):
		TexLoc = (tex*0x800+0x14AB8)
		if tex==3:
			gname = 'segment2.{:05X}.ia16'.format(TexLoc+nameOff)
		else:
			gname = 'segment2.{:05X}.rgba16'.format(TexLoc+nameOff)
		glyph = BinPNG.MakeImage(str(Seg2 / gname))
		loc = s.B2P(Seg2Location+TexLoc)
		bin = rom[loc:loc+0x800]
		if tex==3:
			BinPNG.IA(32,32,16,bin,glyph)
		else:
			BinPNG.RGBA16(32,32,bin,glyph)

def ExportInternalName(rom,src):
	IntNameS = open(src/'extras'/'rm2c'/'internal_name.s','w')
	IntNameS.write(".byte ")
	for i in range(20):
		comma = ','*(i!=19)
		IntNameS.write("0x{:x}{}".format(struct.unpack(">B",rom[0x20+i:0x21+i])[0],comma))

def ExportTextureScrolls(Scripts,rootdir):
	game = rootdir/'src'/'extras'/'rm2c'
	os.makedirs(game,exist_ok=True)
	ST = game/'scroll_texture.inc.c'
	ST = open(ST,'w')
	ST.write(ScrollTargetHead)
	x=0
	arr = []
	for s in Scripts:
		for scroll in s.ScrollArray:
			ST.write('extern Vtx {}[];\n'.format(scroll[0]))
			arr.append(' &{}[{}],\n'.format(scroll[0],scroll[1]))
	ST.write('Vtx *ScrollTargets[]={\n')
	[ST.write(a) for a in arr]
	ST.write('};')
	ST.close()

#Rip misc data that may or may not need to be ported. This currently is trajectories and star positions.
#Do this if misc or 'all' is called on a rom.
def ExportMisc(rom,rootdir,editor):
	#export internal name
	src = rootdir/'src'
	s = Script(9)
	misc = rootdir/'src'/'extras'/'rm2c'
	os.makedirs(misc,exist_ok=True)
	ExportInternalName(rom,src)
	StarPos = misc/('star_pos.inc.c')
	Trajectory = misc/('trajectories.inc.c')
	#Trajectories are by default in the level bank, but moved to vram for all hacks
	#If your trajectory does not follow this scheme, then too bad
	Trj = open(Trajectory,'w')
	Trj.write("""#include <PR/ultratypes.h>
#include "level_misc_macros.h"
#include "macros.h"
#include "types.h"
""")
	for k,v in Trajectories.items():
		Dat = UPA(rom,v,'>L',4)[0]
		#loaded via asm, gonna use cringe for now. RM load isn't consistant since RM has been poopy on penguins
		if k=='ccm_seg7_trajectory_penguin_race_RM2C':
			#defualt value
			if Dat==1006896898:
				pass
			else:
				if editor:
					Dat=0x80405A00
				else:
					Dat=0x80405A00
		#Check if Dat is in a segment or not
		if Dat>>24!=0x80:
			Trj.write('//%s Has the default vanilla value or an unrecognizable pointer\n\n'%k)
			Trj.write(DefaultTraj[k])
		else:
			Trj.write('const Trajectory {}_path[] = {{\n'.format(k))
			Dat = Dat-0x7F200000
			x=0
			while(True):
				point = UPA(rom,Dat+x,'>4h',8)
				if point[0]==-1:
					break
				Trj.write('\tTRAJECTORY_POS({},{},{},{}),\n'.format(*point))
				x+=8
			Trj.write('\tTRAJECTORY_END(),\n};\n')
	#Star positions
	SP = open(StarPos,'w')
	#pre editor and post editor do star positions completely different.
	#I will only be supporting post editor as the only pre editor hack people care
	#about is sm74 which I already ported.
	for k,v in StarPositions.items():
		#different loading schemes for depending on if a function or array is used for star pos
		if v[0]:
			pos = [UPA(rom,a[1],a[0],a[2])[0] for a in v[:-2]]
			SP.write("#define {}StarPos {} {}, {}, {} {}\n".format(k,v[-2],*pos,v[-1]))
		else:
			if editor:
				pos = UPF(rom,v[2])
			else:
				pos = UPF(rom,v[1])
			if UPA(rom,v[1],">L",4)[0]==0x01010101:
				SP.write(DefaultPos[k])
			else:
				SP.write("#define {}StarPos {}f, {}f, {}f\n".format(k,*pos))
	#item box. In vanilla its at 0xEBBA0, RM is at 0x1204000 or sm64 tweaker
	#the struct is 4*u8 (id, bparam1, bparam2, model ID), bhvAddr u32
	ItemBox = 0x1204000
	#some hacks move this so I want to put a stop in just in case
	stop=ItemBox+0x800
	IBox = misc/('item_box.inc.c')
	IBox = open(IBox,'w')
	IBox.write("""#include "sm64.h"
""")
	IBox.write('struct ExclamationBoxContents sExclamationBoxContents[] = { ')
	f=0
	while(True):
		B = UPA(rom,ItemBox,">4B",4)
		#The location has not been changed.
		if f==0 and B[0]==1:
			ItemBox=0xEBBA0
			f=1
			continue
		f=1
		if B[0]==99:
			break
		Bhv = s.GetLabel("{:08x}".format(UPA(rom,ItemBox+4,">L",4)[0]))
		ItemBox+=8
		IBox.write("{{ {}, {}, {}, {}, {} }},\n".format(*B,Bhv))
		if ItemBox>stop:
			break
	IBox.write("{ 99, 0, 0, 0, NULL } };\n")
	ExportTweaks(rom,rootdir)

#This gets exported with misc, but is a separate function
def ExportTweaks(rom,rootdir):
	misc = rootdir/'src'/'extras'/'rm2c'
	os.makedirs(misc,exist_ok=True)
	twk = open(misc/'tweaks.h','w')
	twk.write("""//This is a series of defines to edit commonly changed parameters in romhacks
//These are commonly referred to as tweaks
""")
	for tweak in Tweaks:
		len = tweak[0]
		res = []
		for i in range(len):
			#type,len,offset,func
			arr = tweak[2][i*4:i*4+4]
			#UPA(rom, offset, type, len)
			res.append(arr[3](UPA(rom,arr[2],arr[0],arr[1])))
		val = repr(res)[1:-1].replace("'","")
		twk.write('#define {} {}\n'.format(tweak[1],val))
	#Stuff idk how/haven't gotten to yet in rom but is still useful to have as a tweak
	twk.write(unkDefaults)
	twk.close()

def AsciiConvert(num):
	#numbers start at 0x30
	if num<10:
		return chr(num+0x30)
	#capital letters start at 0x41
	elif num<0x24:
		return chr(num+0x37)
	#lowercase letters start at 0x61
	elif num<0x3E:
		return chr(num+0x3D)
	else:
			return TextMap[num]

#seg 2 is mio0 compressed which means C code doesn't translate to whats in the rom at all.
#This basically means I have to hardcode offsets, it should work for almost every rom anyway.
def ExportText(rom,rootdir,TxtAmt):
	s = Script(9)
	DiaTbl = s.B2P(0x0200FFC8)
	text = rootdir/"text"/'us'
	os.makedirs(text,exist_ok=True)
	textD = text/("dialogs.h")
	textD = open(textD,'w',encoding="utf-8")
	UPW = (lambda x,y: struct.unpack(">L",x[y:y+4])[0])
	#format is u32 unused, u8 lines/box, u8 pad, u16 X, u16 width, u16 pad, offset
	DialogFmt = "int:32,2*uint:8,3*uint:16,uint:32"
	for dialog in range(0,TxtAmt*16,16):
		StrSet = BitArray(rom[DiaTbl+dialog:DiaTbl+16+dialog])
		StrSet = StrSet.unpack(DialogFmt)
		#mio0 compression messes with banks and stuff it just werks
		Mtxt = s.B2P(StrSet[6])
		str = ""
		while(True):
			num = rom[Mtxt:Mtxt+1][0]
			if num!=0xFF:
				str+=AsciiConvert(num)
			else:
				break
			Mtxt+=1
		textD.write('DEFINE_DIALOG(DIALOG_{0:03d},{1:d},{2:d},{3:d},{4:d}, _("{5}"))\n\n'.format(int(dialog/16),StrSet[0],StrSet[1],StrSet[3],StrSet[4],str))
	textD.close()
	#now do courses
	courses = text/("courses.h")
	LevelNames = 0x8140BE
	courses = open(courses,'w',encoding="utf-8")
	for course in range(26):
		name = s.B2P(UPW(rom,course*4+LevelNames))
		str = ""
		while(True):
			num = rom[name:name+1][0]
			if num!=0xFF:
				str+=AsciiConvert(num)
			else:
				break
			name+=1
		acts = []
		ActTbl = 0x814A82
		if course<15:
			#get act names
			for act in range(6):
				act = s.B2P(UPW(rom,course*24+ActTbl+act*4))
				Actstr=""
				while(True):
					num = rom[act:act+1][0]
					if num!=0xFF:
						Actstr+=AsciiConvert(num)
					else:
						break
					act+=1
				acts.append(Actstr)
			courses.write("COURSE_ACTS({}, _(\"{}\"),\t_(\"{}\"),\t_(\"{}\"),\t_(\"{}\"),\t_(\"{}\"),\t_(\"{}\"),\t_(\"{}\"))\n\n".format(Course_Names[course],str,*acts))
		elif course<25:
			courses.write("SECRET_STAR({}, _(\"{}\"))\n".format(course,str))
		else:
			courses.write("CASTLE_SECRET_STARS(_(\"{}\"))\n".format(str))
	#do extra text
	Extra = 0x814A82+15*6*4
	for i in range(7):
		Ex=s.B2P(UPW(rom,Extra+i*4))
		str=""
		while(True):
			num = rom[Ex:Ex+1][0]
			if num!=0xFF:
				str+=AsciiConvert(num)
			else:
				break
			Ex+=1
		courses.write("EXTRA_TEXT({},_(\"{}\"))\n".format(i,str))
	courses.close()

def ExportWaterBoxes(AllWaterBoxes,rootdir):
	misc = rootdir/'src'/'extras'/'rm2c'
	os.makedirs(misc,exist_ok=True)
	MovtexEdit = misc/"water_box.inc.c"
	AllWaterBoxes.sort(key=(lambda x: [x[1],x[2],x[3]])) #level,area,type
	if not AllWaterBoxes:
		print("no water boxes")
		return
	MTinc = open(MovtexEdit,'w')
	MTinc.write(infoMsg)
	for a in AllWaterBoxes:
		MTinc.write("extern u8 "+a[0]+"[];\n")
	MTinc.write("\nstatic void *RM2C_Water_Box_Array[33][8][3] = {\n")
	AreaNull = "{"+"NULL,"*3+"},"
	LevelNull = "{ "+AreaNull*8+" },\n"
	LastL = 3
	LastA = -1
	LastType=0
	first = 0
	for wb in AllWaterBoxes:
		L = wb[1]
		A = wb[2]
		T = wb[3]
		if (A!=LastA or L!=LastL) and first!=0:
			for i in range(2-LastType):
				MTinc.write("NULL,")
			MTinc.write("},")
		if L!=LastL and first!=0:
			LastType = 0
			for i in range(7-LastA):
				MTinc.write(AreaNull)
			LastA = -1
			MTinc.write(" },\n")
		for i in range(L-LastL-1):
			MTinc.write(LevelNull)
		if first==0 or L!=LastL:
			MTinc.write("{ ")
		for i in range(A-LastA-1):
			MTinc.write(AreaNull)
		for i in range(T-LastType-1):
			MTinc.write("NULL,")
		if T==0:
			MTinc.write("{")
		MTinc.write("&%s,"%wb[0])
		LastL = L
		LastA = A
		LastType = T
		first=1
	for i in range(2-LastType):
		MTinc.write("NULL,")
	MTinc.write("},")
	for i in range(7-LastA):
		MTinc.write(AreaNull)
	MTinc.write(" }\n};\n")
	func = """
void *GetRomhackWaterBox(u32 id){
id = id&0xF;
return RM2C_Water_Box_Array[gCurrLevelNum-4][gCurrAreaIndex][id];
};"""
	MTinc.write(func)

def ExportTitleScreen(rom,level):
	#8016f904,8016f908
	UPH = (lambda x,y: struct.unpack(">h",x[y:y+2])[0])
	titleptr = UPH(rom,0x0021FDC6)<<16
	titleptr += UPH(rom,0x0021FDCA)
	#choose level
	s = Script(0)
	s.editor=0
	global Seg15Location
	entry = Seg15Location
	#get all level data from script
	while(True):
		#parse script until reaching special
		q=PLC(rom,entry)
		#execute special cmd
		entry = jumps[q[0]](rom,q,q[3],s)
		#I assume no one messed with the entry script
		#or else this will fail hard. I have to exit manually
		#early because the title screen is overwritten quickly
		if entry>=2531020:
			break
	#somehow title screens have issues
	try:
		Rtitleptr = s.B2P(titleptr)
	except:
		return
	intro = level/'intro'
	intro.mkdir(exist_ok=True)
	WriteModel(rom,[[Rtitleptr,titleptr]],s,intro,'TITLESCREEN','intro_seg7_',intro,False)
	#Make leveldata.c for intro
	ld = intro/ 'leveldata.c'
	ld = open(ld,'w')
	ld.write(TitleStrFormatter.format('DL_intro_seg7_0x%x'%titleptr))
	ld.close()
	#Export file/star select textures manually
	#continue script parsing until new bank 7 is reached
	while(True):
		#parse script until reaching special
		q=PLC(rom,entry)
		#execute special cmd
		entry = jumps[q[0]](rom,q,q[3],s)
		#I assume no one messed with the entry script
		#or else this will fail hard. I have to exit manually
		#early because the title screen is overwritten quickly
		if entry>=0x2abca0:
			break
	menu = level/'menu'
	menu.mkdir(exist_ok=True)
	#format is name,seg addr,size, binsize. All textures are RGBA16 fmt
	for tex in Seg7Textures:
		img = BinPNG.MakeImage(str(menu / tex[0]))
		loc= s.B2P(0x07000000+tex[1])
		bin = rom[loc:loc+tex[3]]
		BinPNG.RGBA16(*tex[2],bin,img)
  
from capstone import *

class JALCall:
    def __init__(self, a0=0, a1=0, a2=0, a3=0, jal_addr=0):
        self.a0 = a0
        self.a1 = a1
        self.a2 = a2
        self.a3 = a3
        self.jal_addr = jal_addr

    def __repr__(self):
        return f"JALCall(a0=0x{self.a0:X}, a1=0x{self.a1:X}, a2=0x{self.a2:X}, a3=0x{self.a3:X}, jal_addr=0x{self.jal_addr:X})"

def findJalsInFunc(rom_bytes, ram_func, ram_to_rom):
    md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32 + CS_MODE_BIG_ENDIAN)
    func_offset = ram_func - ram_to_rom
    code = rom_bytes[func_offset:func_offset + 0x1000]
    instructions = list(md.disasm(code, ram_func))

    calls = []
    reg_state = {"a0": 0, "a1": 0, "a2": 0, "a3": 0}
    jal_addr = 0
    add_next_time = False

    gp_register_values = {reg: 0 for reg in ["a0", "a1", "a2", "a3", "r0"]}

    def parse_imm(s):
        return int(s, 0)  # handles hex, decimal, negative hex

    def reg_name(r):
        return r.lower()

    for ins in instructions:
        op = ins.mnemonic
        args = ins.op_str.replace("$", "").split(", ")
        
        # normalize
        if len(args) < 3:
            args += [None] * (3 - len(args))

        if op == "lui":
            dest = reg_name(args[0])
            imm = parse_imm(args[1]) if args[1] else 0
            if dest in reg_state:
                reg_state[dest] = imm << 16
                gp_register_values[dest] = reg_state[dest]

        elif op == "addiu":
            dest = reg_name(args[0])
            src = reg_name(args[1])
            imm = parse_imm(args[2]) if args[2] else 0

            if dest in reg_state:
                if dest == src:
                    # aX += immediate
                    reg_state[dest] += imm
                elif src == "r0":
                    # aX = immediate
                    reg_state[dest] = imm
                else:
                    reg_state[dest] = imm + gp_register_values.get(src, 0)

                gp_register_values[dest] = reg_state[dest]

        elif op == "ori":
            dest = reg_name(args[0])
            src = reg_name(args[1])
            imm = parse_imm(args[2]) if args[2] else 0

            if dest in reg_state:
                if dest == src:
                    # aX |= immediate 16
                    reg_state[dest] |= imm & 0xFFFF
                elif src == "r0":
                    # aX = immediate
                    reg_state[dest] = imm
                else:
                    # aX = immediate | gp_register_values[src]
                    reg_state[dest] = imm | gp_register_values.get(src, 0)

                gp_register_values[dest] = reg_state[dest]

        elif op == "jal":
            target = 0
            try:
                target = int(args[0], 0)
            except Exception:
                target = ins.operands[0].imm if ins.operands else 0

            jal_addr = (ins.address & 0xF0000000) | (target << 2)
            add_next_time = True

        if add_next_time:
            calls.append(JALCall(
                a0=reg_state["a0"],
                a1=reg_state["a1"],
                a2=reg_state["a2"],
                a3=reg_state["a3"],
                jal_addr=jal_addr
            ))
            add_next_time = False

    return calls

def main(levels = [], actors = [], editor = False, rom = '', Append = [], WaterOnly = 0, ObjectOnly = 0,
MusicOnly = 0, MusicExtend = 0, Text = None, Misc = None, Textures = 0, Inherit = 0, Upscale = 0,
Title = 0, Sound = 0, Objects = 0, skipTLUT = False):
	#This is not an arg you should edit really
	TxtAmount = 170
	romname = rom.split(".")[0]
	fullromname = rom
	rom = open(rom,'rb')
	global RomDataGlobal
	RomDataGlobal = rom = rom.read()
	root = sys.path[0]
	#find segments
	global Seg2Location
	global Seg2LocationEnd
	Funcs = findJalsInFunc(rom, 0x80248964, 0x80245000) #ok so, seg2 export is fucked, how
	for call in Funcs:
		if call.a0 == 0x2:
			Seg2Location = call.a1
			Seg2LocationEnd = call.a2
			print(f"Found Segment 0x2: 0x{Seg2Location:08X} - 0x{Seg2LocationEnd:08X}")
			if Seg2Location==0x800000:
				Seg2Location=0x02000000
			break
	UPH2 = (lambda rom,addr: struct.unpack(">I", rom[addr:addr+4])[0])
	global Seg15Location
	Seg15Location = UPH2(rom, 0x2A622C)
	Seg15LocationEnd = UPH2(rom, 0x2A6230)
	print(f"Found Segment 0x15: 0x{Seg15Location:08X} – 0x{Seg15LocationEnd:08X}")
	#Export dialogs and course names
	if (Text or levels=='all') and Text!=0:
		for A in Append:
			Arom = open(A[0],'rb')
			Arom = Arom.read()
			ExportText(Arom,Path(root),TxtAmount)
		ExportText(rom,Path(root),TxtAmount)
		print('Text Finished')
	#Export misc data like trajectories or star positions.
	if (Misc or levels=='all') and Misc!=0:
		for A in Append:
			Arom = open(A[0],'rb')
			Arom = Arom.read()
			ExportMisc(Arom,Path(root),A[2])
		ExportMisc(rom,Path(root),editor)
		print('Misc Finished')
	print('Starting Export')
	AllWaterBoxes = []
	m64s = []
	seqNums = []
	Onlys = [WaterOnly,ObjectOnly,MusicOnly]
	#clean sound dir
	sound = Path(root) / 'sound'
	if not Inherit:
		if os.path.isdir(sound):
			shutil.rmtree(sound)
	#custom level defines file so the linker knows whats up. Mandatory or export won't work
	lvldir = Path(root) / 'levels'
	#So you don't have truant level folders from a previous export
	if not Inherit:
		if os.path.isdir(lvldir):
			shutil.rmtree(lvldir)
	lvldir.mkdir(exist_ok=True)
	lvldefs = lvldir/"custom_level_defines.h"
	lvldefs = open(lvldefs,'w')
	ass=Path("actors")
	ass=Path(root)/ass
	if not Inherit and (actors or Objects):
		if os.path.isdir(ass):
			shutil.rmtree(ass)
	ass.mkdir(exist_ok=True)
	#Array of all scripts from each level
	Scripts = []
	if levels=='all':
		for k in Num2Name.keys():
			s = ExportLevel(rom,k,editor,Append,AllWaterBoxes,Onlys,romname,m64s,seqNums,MusicExtend,lvldefs,skipTLUT)
			Scripts.append(s)
			print(GetlevelName(k) + ' done')
	else:
		for k in levels:
			s = ExportLevel(rom,k,editor,Append,AllWaterBoxes,Onlys,romname,m64s,seqNums,MusicExtend,lvldefs,skipTLUT)
			Scripts.append(s)
			print(GetlevelName(k) + ' done')
	lvldefs.close()
	gc.collect() #gaurantee some mem is freed up.
	#Export texture scrolls
	ExportTextureScrolls(Scripts,Path(root))
	#export title screen via arg
	if Title:
		ExportTitleScreen(rom,lvldir)
	#Process returned scripts to view certain custom data such as custom banks/actors for actor/texture exporting
	[Banks,Models,ObjectD] = ProcessScripts(rom,editor,Scripts)
	if actors:
		ExportActors(actors,rom,Models,ass)
	#Behaviors
	if Objects:
		ExportObjects(Objects,ObjectD,rom,ass,Path(root),editor)
	#export textures
	if Textures:
		ExportTextures(rom,editor,Path(root),Banks,Inherit)
	#AllWaterBoxes should have refs to all water boxes, using that, I will generate a function
	#and array of references so it can be hooked into moving_texture.c
	#example of AllWaterBoxes format [[str,level,area,type]...]
	if not (MusicOnly or ObjectOnly):
		ExportWaterBoxes(AllWaterBoxes,Path(root))
	if not (WaterOnly or ObjectOnly):
		RipNonLevelSeq(rom,m64s,seqNums,Path(root),MusicExtend,romname)
		CreateSeqJSON(rom,list(zip(m64s,seqNums)),Path(root),MusicExtend)
		if Sound:
			RipInstBanks(fullromname,Path(root))
	Log.WriteWarnings()
	print('Export Completed, see ImportInstructions.py for potential errors when importing to decomp')
	print('If the ROM imported uses MOP, make sure to set PORT_MOP_OBJS=1 when compiling')
	print('If the ROM imported has 3D Coins, follow the extra steps in README.md')

#evaluate a system argument in a way that is easier to manage and specific to the
#arguments I intend to take
def EvalArg(name, arg):
	if name == 'rom':
		a = Path(arg)
		if a.exists() or 1:
			return arg
		raise Exception(f"ROM file {arg} is not found in this directory")
	elif name == 'levels' or name == 'actors' or name == 'Objects':
		if arg == 'all' or arg == 'new' or arg == 'all_new':
			return arg
		else:
			try:
				return eval(arg)
			except:
				raise Exception(f"Argument {name} unable to be evaluated with arg {arg}")
	else:
		try:
			return eval(arg)
		except:
			raise Exception(f"Argument {name} unable to be evaluated with arg {arg}")

if __name__=='__main__':
	argD = {}
	args = ''
	if any(h in sys.argv for h in ["-h", "help", "--help"]):
		print(HelpMsg)
		if any(h in sys.argv for h in ["-v", "verbose", "--verbose"]):
			print(Verbose)
		sys.exit()
	for arg in sys.argv[1:]:
		args+=arg+" "
	try:
		#the utmosts of cringes
		for arg in sys.argv:
			if arg=='RM2C.py':
				continue
			arg = arg.split('=')
			argD[arg[0]]=EvalArg(arg[0], arg[1])
	except:
		print(Invalid_Input,HelpMsg,Invalid_Input)
		a = '" "'.join(sys.argv[1:])
		a = f"python3 RM2C.py \"{a}\""
		print("If you are using terminal try using this\n"+a)
		raise 'bad arguments'
	main(**argD)
	# with cProfile.Profile() as pr:
		# main(**argD)
	# stats = pstats.Stats(pr)
	# stats.sort_stats(pstats.SortKey.CUMULATIVE)
	# stats.print_stats()
	# stats.dump_stats(filename='profile.prof')
