
------------------Invalid Input - Error ------------------
 
Arguments for RM2C are as follows:
rom=romname editor=False levels=[] actors=[] Objects=0
Append=[("romname",areaoffset,editor),...]
WaterOnly=0 ObjectOnly=0 MusicOnly=0 MusicExtend=0
Text=0 Misc=0 Textures=0 Inherit=0 Upscale=0 Title=0 Sound=0

Arguments with equals sign are shown in default state, do not put commas between args.
String args do not require quotes unless it is within the Append argument. When using quotes, or paranthesis, make sure you properly escape the characters with '' depending on your platform.

Example input1 (all actor models in BoB):
python RM2C.py rom=ASA.z64 editor=True levels=[9] actors=all ObjectOnly=1

Example input2 (Export all Levels in a RM rom):
python RM2C.py rom=baserom.z64 levels=all

Example input3 (Export all BoB in a RM rom with a second area from another rom):
python RM2C.py rom=baserom.z64 levels=all Append=[('rom2.z64',1,True)]

NOTE! if you are on unix bash requires you to escape certain characters. For this module, these
are quotes and paranthesis. Add in a escape before each.

example: python3 RM2C.py rom=sm74.z64 levels=[9] Append=[\('sm74EE.z64',1,1\)] editor=1
 
------------------Invalid Input - Error ------------------

If you are using terminal try using this
python3 RM2C.py "rom=impak.z64" "levels=[9]"
