'''ALL QuBit Manipulations'''

from colorama import init, Fore, Back
init(autoreset=True) #to convert termcolor to wins color

from os.path import basename as bs
mdlname = bs(__file__).split('.')[0] # instrument-module's name e.g. ENA, PSG, YOKO

from time import time, sleep
from copy import copy, deepcopy
from json import loads, dumps
from numpy import prod, array, mean, ceil
from flask import session, g

from importlib import import_module as im
from pyqum.instrument.logger import settings, get_status, set_status, jobsinqueue, qout, job_update_perimeter
from pyqum.instrument.toolbox import cdatasearch, waveform, find_in_list
from pyqum.instrument.composer import pulser
from pyqum.instrument.analyzer import pulse_baseband
from pyqum.instrument.reader import inst_order


__author__ = "Teik-Hui Lee"
__copyright__ = "Copyright 2019, The Pyqum Project"
__credits__ = ["Chii-Dong Chen"]
__license__ = "GPL"
__version__ = "beta3"
__email__ = "teikhui@phys.sinica.edu.tw"
__status__ = "development"

# region: 1. Single-Qubit Control:
# **********************************************************************************************************************************************************
@settings(2) # data-density
def Single_Qubit(owner, tag="", corder={}, comment='', dayindex='', taskentry=0, resumepoint=0, instr={}, perimeter={}):
    '''
    Time-domain Square-wave measurement:\n
    SCORES (SCripted ORchestration of Entanglement & Superposition) is a scripted pulse instruction language for running Quantum Algorithm.\n
    perimeter.keys() = ['XY-LO-Power', 'RO-LO-Power', 'SCORE-NS', 'SCORE-JSON', 'R-JSON', 'RECORD-SUM', 'RECORD_TIME_NS', 'READOUTYPE']\n
    C-Structure = ['Flux-Bias', 'XY-LO-Frequency', 'RO-LO-Frequency'] + [...R-parameter(s)...]\n
    Differ from previous directive, this version onward, our stored data will assume the following form:\n
    DATA = STRUCTURE + BUFFER (Thus ALL part of Structure will now participate in measure-loop)
    '''

    # DR-1 settings:
    # instr['DC'], instr['SG'], instr['DAC'], instr['ADC'] = 'YOKO_2', ['PSGA_2', 'PSGV_1'], 'TKAWG_1', 'ALZDG_1'

    # User-specific settings in JSON:
    sample = get_status("MSSN")[session['user_name']]['sample']
    queue = get_status("MSSN")[session['user_name']]['queue']

    # Loading Channel-Settings:
    CH_Wiring = inst_order(queue, 'CH')
    DACH_Matrix = CH_Wiring['DAC']
    ROLE_Wiring = inst_order(queue, 'ROLE')
    DACH_Role = ROLE_Wiring['DAC']
    RO_addr = find_in_list(DACH_Role, 'I1')
    XY_addr = find_in_list(DACH_Role, 'X1')
    print(Fore.YELLOW + "RO_addr: %s, XY_addr: %s" %(RO_addr,XY_addr))

    # Queue-specific instrument-package in list:
    instr['DC']= inst_order(queue, 'DC')[0]
    instr['SG']= inst_order(queue, 'SG')
    instr['DAC']= inst_order(queue, 'DAC')
    instr['ADC']= inst_order(queue, 'ADC')[0]

    # Packing instrument-specific perimeter from database:
    perimeter.update(dict(TIME_RESOLUTION_NS=loads(g.machspecs[instr['ADC']])['TIME_RESOLUTION_NS']))
    perimeter.update(dict(CLOCK_HZ=loads(g.machspecs[instr['DAC'][0]])['CLOCK_HZ']))
    # Packing wiring-specific perimeter from database:
    perimeter.update(dict(CH_Wiring=dumps(CH_Wiring)))
    perimeter.update(dict(ROLE_Wiring=dumps(ROLE_Wiring)))

    # pushing pre-measurement parameters to settings:
    yield owner, sample, tag, instr, corder, comment, dayindex, taskentry, perimeter, queue

    # ***USER_DEFINED*** Controlling-PARAMETER(s) ======================================================================================
    # 1a. Instruments' specs:
    TIME_RESOLUTION_NS = int(perimeter['TIME_RESOLUTION_NS'])
    CLOCK_HZ = float(perimeter['CLOCK_HZ'])
    # 1b. DSP perimeter(s)
    digital_homodyne = perimeter['DIGIHOME']
    ifreqcorrection_kHz = float(perimeter['IF_ALIGN_KHZ'])
    # 1c. Basic perimeter(s): # previously: config = corder['C-Config']
    biasmode = bool(int(perimeter['BIASMODE']))
    xypowa = perimeter['XY-LO-Power']
    ropowa = perimeter['RO-LO-Power']
    trigger_delay_ns = int(perimeter['TRIGGER_DELAY_NS'])
    recordsum = int(perimeter['RECORD-SUM'])
    recordtime_ns = int(perimeter['RECORD_TIME_NS']) # min:1280ns, step:128ns
    readoutype = perimeter['READOUTYPE']
    # 1d. Pulse parameters:
    SCORE_TEMPLATE = perimeter['SCORE-JSON'] # already a DICT
    RJSON = loads(perimeter['R-JSON'].replace("'",'"'))
    # 1e. Derived perimeter(s) from above:
    ifperiod = pulser(score=SCORE_TEMPLATE['CH%s'%RO_addr]).totaltime
    RO_Compensate_MHz = -pulser(score=SCORE_TEMPLATE['CH%s'%RO_addr]).IF_MHz_rotation # working with RO-MOD (up or down)
    XY_Compensate_MHz = -pulser(score=SCORE_TEMPLATE['CH%s'%XY_addr]).IF_MHz_rotation # working with XY-MOD (up or down)
    print(Fore.YELLOW + "RO_Compensate_MHz: %s, XY_Compensate_MHz: %s" %(RO_Compensate_MHz,XY_Compensate_MHz))
    skipoints = 0
    try: 
        if (digital_homodyne=="i_digital_homodyne" or digital_homodyne=="q_digital_homodyne"): skipoints = int(ceil( 1 / abs(RO_Compensate_MHz) * 1000 ))
    except: 
        print(Fore.RED + "WARNING: INFINITE INTEGRATION IS NOT PRACTICAL!")
    # print(Fore.CYAN + "Skipping first %s point(s)" %skipoints)

    # 2a. Basic corder / parameter(s):
    structure = corder['C-Structure'] + [k for k in RJSON.keys()]
    fluxbias = waveform(corder['Flux-Bias'])
    xyfreq = waveform(corder['XY-LO-Frequency'])
    rofreq = waveform(corder['RO-LO-Frequency'])
    for k in RJSON.keys(): corder[k] = RJSON[k] # update corder with R-parameters
    # 2b. Prepare R-waveform object for pulse-instructions
    R_waveform = {}
    for k in RJSON.keys(): R_waveform[k] = waveform(RJSON[k])
    
    # Pre-loop settings:
    # Optionals:
    # DC:
    [DC_type, DC_label] = instr['DC'].split('_')
    if "DUMMY" not in DC_type.upper(): DC = im("pyqum.instrument.machine.%s" %DC_type)
    if "opt" not in fluxbias.data: # check if it is in optional-state / serious-state
        dcbench = DC.Initiate(current=biasmode, which=DC_label) # pending option
        DC.output(dcbench, 1)

    # SG for [XY, RO]:
    SG_qty = len(instr['SG'])
    SG_type, SG_label, SG, SG_instance, SG_freq, SG_powa = [None]*SG_qty, [None]*SG_qty, [None]*SG_qty, [None]*SG_qty, [xyfreq.data, rofreq.data], [xypowa, ropowa]
    for i in range(SG_qty):
        [SG_type[i], SG_label[i]] = instr['SG'][i].split('_')
        SG[i] = im("pyqum.instrument.machine.%s" %SG_type[i])
        if "opt" not in SG_freq[i]: # check if it is in optional-state / serious-state
            SG_instance[i] = SG[i].Initiate(which=SG_label[i])
            SG[i].power(SG_instance[i], action=['Set', str(SG_powa[i]) + ""]) # UNIT dBm NOT WORKING IN DDSLO
            SG[i].rfoutput(SG_instance[i], action=['Set', 1])
            # if SG_type[i] in 'DDSLO,...' and i==1: # Set CH-2 for DDSLO(-2) type of SG (PENDING: BASED ON WIRING DATABASE instead)
            #     SG[i].power(SG_instance[i], action=['Set_2', str(SG_powa[i]) + ""]) # UNIT dBm NOT WORKING IN DDSLO
            #     SG[i].rfoutput(SG_instance[i], action=['Set_2', 1])

    # DAC for [ROXY]:
    DAC_qty = len(instr['DAC'])
    DAC_type, DAC_label, DAC, DAC_instance = [None]*DAC_qty, [None]*DAC_qty, [None]*DAC_qty, [None]*DAC_qty
    # PENDING: ASSIGN according to instr['CH']
    # if DAC_qty>1: DACH_Matrix = [[1,2,3,4],[1,2]] # [[RO-I,RO-Q,Z1,Z2],[XY-I,XY-Q]]
    # elif DAC_qty==1: DACH_Matrix = [[1,2,3,4]] # [[RO-I,RO-Q,XY-I,XY-Q]]

    for i, channel_set in enumerate(DACH_Matrix):
        [DAC_type[i], DAC_label[i]] = instr['DAC'][i].split('_')
        DAC[i] = im("pyqum.instrument.machine.%s" %DAC_type[i])
        DAC_instance[i] = DAC[i].Initiate(which=DAC_label[i])
        DAC[i].clock(DAC_instance[i], action=['Set', 'EFIXed', CLOCK_HZ])
        DAC[i].clear_waveform(DAC_instance[i],'all')
        DAC[i].alloff(DAC_instance[i], action=['Set',1])
        
        # PENDING: Extract the settings from the machine database instead.
        if i==0: 
            markeroption = 7
            update_settings = dict(Master=True, trigbyPXI=2, markeroption=7) # First-in-line = Master (usually RO giving Trigger through CH-4)
        else: 
            markeroption = 0
            update_settings = dict(Master=False, trigbyPXI=2)
        print(Fore.CYAN + "%s's setting: %s" %(instr['DAC'][i], update_settings))

        '''Prepare DAC:'''
        dt = round(1/float(DAC[i].clock(DAC_instance[i])[1]['SRATe'])/1e-9, 2)
        pulseq = pulser(dt=dt, clock_multiples=1, score="ns=%s"%ifperiod)
        # pulseq = pulser(dt, clock_multiples=1, score="ns=300000;FLAT/,3000,0.01;")
        pulseq.song()
        for channel in channel_set:
            DAC[i].prepare_DAC(DAC_instance[i], int(channel), pulseq.totalpoints, update_settings=update_settings)
        for channel in channel_set:
            DAC[i].compose_DAC(DAC_instance[i], int(channel), pulseq.music, [], markeroption) # we don't need marker yet initially
        # Turn on all 4 channels:
        DAC[i].alloff(DAC_instance[i], action=['Set',0])
        DAC[i].ready(DAC_instance[i])
        DAC[i].play(DAC_instance[i])
    
    # ADC:
    [ADC_type, ADC_label] = instr['ADC'].split('_')
    ADC = im("pyqum.instrument.machine.%s" %ADC_type)
    adca = ADC.Initiate(which=ADC_label)
    '''Prepare ADC:'''
    TOTAL_POINTS = round(recordtime_ns / TIME_RESOLUTION_NS)
    update_items = dict( triggerDelay_sec=trigger_delay_ns*1e-9, TOTAL_POINTS=TOTAL_POINTS, NUM_CYCLES=recordsum, PXI=-13 ) # HARDWIRED to receive trigger from the front-panel EXT.
    ADC.ConfigureBoard(adca, update_items)
    

    # Buffer-size for lowest-bound data-collecting instrument:
    if readoutype == 'one-shot': # for fidelity measurement
        buffersize = recordsum * 2 # data-density of 2 due to IQ
        print("Buffer-size: %s" %buffersize)
    else: # by default we usually take average
        buffersize = TOTAL_POINTS * 2 # data-density of 2 due to IQ
        print("Buffer-size: %s" %buffersize)
    # Total data points to be saved into file:
    datasize = int(prod([waveform(corder[param]).count for param in structure], dtype='uint64')) * buffersize
    print("data size: %s" %datasize)

    # User-defined Measurement-FLOW ==============================================================================================
    
    # 1. Registerring parameter(s)-structure
    cstructure = [waveform(corder[param]).count for param in structure] # new version: separation between structure & buffer

    # 2. Start measuring:
    JOBID = g.jobidlist[0]
    job_update_perimeter(JOBID, perimeter)
    measure_loop = range(resumepoint//buffersize,datasize//buffersize) # saving chunck by chunck improves speed a lot!
    while True:
        for i in measure_loop:
            print(Back.BLUE + Fore.WHITE + 'measure single-qubit %s/%s' %(i+1,datasize//buffersize))
            # determining the index-locations for each parameters, i.e. the address at any instance
            caddress = cdatasearch(i, cstructure)
            print(Fore.BLACK + Back.WHITE + "i: %s, cstructure: %s, caddress: %s" %(i,cstructure,caddress))

            # setting each c-order (From High to Low level of execution):
            # ***************************************************************
            SCORE_DEFINED = deepcopy(SCORE_TEMPLATE)
            for j in range(len(cstructure)): # new version: all part of structure will participate
                if (not i%prod(cstructure[j+1::])) or i==resumepoint//buffersize: # virtual for-loop using exact-multiples condition
                    # print("entering %s-stage" %j)
                    # Optionals:
                    # DC
                    if structure[j] == 'Flux-Bias':
                        if "opt" not in fluxbias.data: # check if it is in optional-state
                            if biasmode: sweeprate = 0.000713  # A-mode A/s
                            else:  sweeprate = 1.37  # V-mode V/s (~10kOhm resistance)
                            DC.sweep(dcbench, str(fluxbias.data[caddress[j]]), sweeprate=sweeprate)

                    # SG
                    elif structure[j] == 'XY-LO-Frequency':
                        if "opt" not in xyfreq.data: # check if it is in optional-state
                            SG[0].frequency(SG_instance[0], action=['Set', str(xyfreq.data[caddress[j]] + XY_Compensate_MHz/1e3) + "GHz"])
                    elif structure[j] == 'RO-LO-Frequency':
                        if "opt" not in rofreq.data: # check if it is in optional-state
                            SG[1].frequency(SG_instance[1], action=['Set_', str(rofreq.data[caddress[j]] + RO_Compensate_MHz/1e3) + "GHz"])
                            # if SG_type[1] in 'DDSLO,...': SG[1].frequency(SG_instance[1], action=['Set_2', str(rofreq.data[caddress[j]] + RO_Compensate_MHz/1e3) + "GHz"])

                # DAC's SCORE-UPDATE:
                if j > 2:
                    # for ch in range(4):
                    for i_slot_order, channel_set in enumerate(DACH_Matrix):
                        for ch in channel_set:
                            # channel = str(ch + 1)
                            dach_address = "%s-%s" %(i_slot_order+1,ch)
                            SCORE_DEFINED['CH%s'%dach_address] = SCORE_DEFINED['CH%s'%dach_address].replace("{%s}"%structure[j], str(R_waveform[structure[j]].data[caddress[j]]))

            # print(Fore.YELLOW + "DEFINED SCORE-CH1: %s" %(SCORE_DEFINED['CH1']))
            # IN THE FUTURE: HVI-ROUTINE STARTS HERE:
            # Basic Control (Every-loop)
            # DAC
            for i_slot_order, channel_set in enumerate(DACH_Matrix):
                # PENDING: Extract the settings from the machine database instead.
                if i_slot_order==0: update_settings = dict(Master=True, clearQ=int(bool(len(channel_set)==4)) ) # First-in-line = Master
                else: update_settings = dict(Master=False, clearQ=int(bool(len(channel_set)==4)) )

                for ch in channel_set:
                    # channel = str(ch + 1)
                    dach_address = "%s-%s" %(i_slot_order+1,ch)
                    pulseq = pulser(dt=dt, clock_multiples=1, score=SCORE_DEFINED['CH%s'%dach_address])
                    pulseq.song()
                    '''
                    NOTE: 
                    TKAWG's marker (number(s)) = SDAWG's markeroption
                    1-4 for TKAWG: ODD-Channel for ARRA-PIN-SWITCH, EVEN-Channel for TRIGGER PURPOSE; RO-TRIGGER: MKR-1: ALZDG, MKR-2: MXA; XY-TRIGGER: MKR-1: MXA, MKR-2: SCOPE
                    7 for SDAWG: PIN-Switch on MixerBox
                    0 for BOTH: disabled.
                    '''
                    # PENDING: edittable markeroption instead of just "2":
                    if (i_slot_order==0) and ("SDAWG" in DAC_type[i_slot_order]): marker = 7
                    else: marker = 2
                    DAC[i_slot_order].compose_DAC(DAC_instance[i_slot_order], int(ch), pulseq.music, pulseq.envelope, marker, update_settings=update_settings) # PENDING: Option to turn ON PINSW for SDAWG (default is OFF)
                DAC[i_slot_order].ready(DAC_instance[i_slot_order])
                print('Waveform from Slot-%s is Ready!'%(i_slot_order+1))
                
            # Basic Readout (Buffer Every-loop):
            # ADC 
            DATA = ADC.AcquireData(adca, recordtime_ns*1e-9, recordsum)[0]
            # POST PROCESSING
            try:
                # TIME EVOLUTION / FIDELITY TEST:
                if readoutype == 'one-shot':
                    DATA = DATA.reshape([recordsum,TOTAL_POINTS*2])
                    if digital_homodyne != "original": 
                        for r in range(recordsum):
                            trace_I, trace_Q = DATA[r,:].reshape((TOTAL_POINTS, 2)).transpose()[0], DATA[r,:].reshape((TOTAL_POINTS, 2)).transpose()[1]
                            trace_I, trace_Q = pulse_baseband(digital_homodyne, trace_I, trace_Q, RO_Compensate_MHz, ifreqcorrection_kHz, dt=TIME_RESOLUTION_NS)
                            DATA[r,:] = array([trace_I, trace_Q]).reshape(2*TOTAL_POINTS) # back to interleaved IQ-Data
                            if not r%1000: print(Fore.YELLOW + "Shooting %s times" %(r+1))
                    DATA = mean(DATA.reshape([recordsum*2,TOTAL_POINTS])[:,skipoints:], axis=1)
                    print(Fore.BLUE + "DATA of size %s is ready to be saved" %len(DATA))
                else: # by default
                    DATA = mean(DATA.reshape([recordsum,TOTAL_POINTS*2]), axis=0)
                    if digital_homodyne != "original": 
                        trace_I, trace_Q = DATA.reshape((TOTAL_POINTS, 2)).transpose()[0], DATA.reshape((TOTAL_POINTS, 2)).transpose()[1]
                        trace_I, trace_Q = pulse_baseband(digital_homodyne, trace_I, trace_Q, RO_Compensate_MHz, ifreqcorrection_kHz, dt=TIME_RESOLUTION_NS)
                        DATA = array([trace_I, trace_Q]).transpose().reshape(TOTAL_POINTS*2) # back to interleaved IQ-Data
            
            except(ValueError):
                # raise # PENDING: UPDATE TIMSUM MISMATCH LIST
                print(Fore.RED + "Check ALZDG OPT_DMA_BUFFER!")
                break # proceed to close all & queue out
            
            # print("Operation Complete")
            print(Fore.YELLOW + "\rProgress-(%s): %.3f%%" %((i+1), (i+1)/datasize*buffersize*100), end='\r', flush=True)			
            
            jobsinqueue(queue)
            if JOBID in g.jobidlist:
                # print(Fore.YELLOW + "Pushing Data into file...")
                yield list(DATA)
            else: break # proceed to close all & queue out

        # PENDING: LISTIFY / DICTIFY THE HANDLE?
        ADC.close(adca, which=ADC_label)
        for i_slot_order, channel_set in enumerate(DACH_Matrix):
            DAC[i_slot_order].alloff(DAC_instance[i_slot_order], action=['Set',1])
            DAC[i_slot_order].close(DAC_instance[i_slot_order], which=DAC_label[i_slot_order])
        if "opt" not in rofreq.data: # check if it is in optional-state
            SG[1].rfoutput(SG_instance[1], action=['Set_', 0])
            if SG_type[1] in 'DDSLO,...': SG[1].rfoutput(SG_instance[1], action=['Set_2', 0])
            SG[1].close(SG_instance[1], SG_label[1], False)
        if "opt" not in xyfreq.data: # check if it is in optional-state
            SG[0].rfoutput(SG_instance[0], action=['Set', 0])
            SG[0].close(SG_instance[0], SG_label[0], False)
        if "opt" not in fluxbias.data: # check if it is in optional-state
            DC.output(dcbench, 0)
            DC.close(dcbench, True, DC_label, sweeprate=sweeprate)
        if JOBID in g.jobidlist:
            qout(queue, g.jobidlist[0],g.user['username'])
        break

    return

# endregion


# region: 2. Multiple-Qubits Control:
# **********************************************************************************************************************************************************
@settings(2) # data-density
def Qubits(owner, tag="", corder={}, comment='', dayindex='', taskentry=0, resumepoint=0, instr={}, perimeter={}):
    '''
    Extension & Improvement on the above:\n

    PENDING:
    1. Scalable & Flexible Parameters: introducing Instrument MACH + M-JSON 
    '''

    # User-specific settings in JSON:
    sample = get_status("MSSN")[session['user_name']]['sample']
    queue = get_status("MSSN")[session['user_name']]['queue']

    # Queue-specific instrument-package in list:
    instr['ROLE']= inst_order(queue, 'ROLE')
    instr['CH']= inst_order(queue, 'CH')
    instr['DC']= inst_order(queue, 'DC')
    instr['SG']= inst_order(queue, 'SG')
    instr['DAC']= inst_order(queue, 'DAC')
    instr['ADC']= inst_order(queue, 'ADC')

    # import relevant instrument control routines:
    instrumentypes, module = [], {}
    for key in instr.keys(): instrumentypes.append([x.split('_')[0] for x in instr[key]])
    instrumentypes = list(dict.fromkeys(instrumentypes)) # to get rid of duplicates
    print(Fore.YELLOW + "Importing %s" %instrumentypes)
    for instr_type in instrumentypes:
        module[instr_type] = im("pyqum.instrument.machine.%s" %instr_type)

    # Packing instrument-specific perimeter from database:
    perimeter.update(dict(TIME_RESOLUTION_NS=g.machspecs[instr['ADC'][0]]))

    # pushing pre-measurement parameters to settings:
    yield owner, sample, tag, instr, corder, comment, dayindex, taskentry, perimeter, queue

    # ***USER_DEFINED*** Controlling-PARAMETER(s) ======================================================================================
    # 1a. DSP perimeter(s)
    digital_homodyne = perimeter['DIGIHOME']
    # rotation_compensate_MHz = float(perimeter['IF_MHZ'])
    ifreqcorrection_kHz = float(perimeter['IF_ALIGN_KHZ'])
    # 1b. Basic perimeter(s): # previously: config = corder['C-Config']
    biasmode = bool(int(perimeter['BIASMODE']))

    # xypowa = perimeter['XY-LO-Power']
    # ropowa = perimeter['RO-LO-Power']
    rf_freq = perimeter['RF-Frequencies']
    rf_powa = perimeter['RF-Powers']

    trigger_delay_ns = int(perimeter['TRIGGER_DELAY_NS'])
    recordsum = int(perimeter['RECORD-SUM'])
    recordtime_ns = int(perimeter['RECORD_TIME_NS']) # min:1280ns, step:128ns
    readoutype = perimeter['READOUTYPE']
    TIME_RESOLUTION_NS = perimeter['TIME_RESOLUTION_NS']
    SCORE_TEMPLATE = perimeter['SCORE-JSON'] # already a DICT
    RJSON = loads(perimeter['R-JSON'].replace("'",'"'))
    # 1b. Derived perimeter(s) from above:
    ifperiod = pulser(score=SCORE_TEMPLATE['CH1']).totaltime
    RO_Compensate_MHz = -pulser(score=SCORE_TEMPLATE['CH1']).IF_MHz_rotation # working with RO-MOD (up or down)
    XY_Compensate_MHz = -pulser(score=SCORE_TEMPLATE['CH3']).IF_MHz_rotation # working with XY-MOD (up or down)
    skipoints = 0
    try: 
        if (digital_homodyne=="i_digital_homodyne" or digital_homodyne=="q_digital_homodyne"): skipoints = int(ceil( 1 / abs(RO_Compensate_MHz) * 1000 ))
    except: 
        print(Fore.RED + "WARNING: INFINITE INTEGRATION IS NOT PRACTICAL!")
    # print(Fore.CYAN + "Skipping first %s point(s)" %skipoints)

    # 2a. Basic corder / parameter(s):
    structure = corder['C-Structure'] + [k for k in RJSON.keys()]
    fluxbias = waveform(corder['Flux-Bias'])

    # xyfreq = waveform(corder['XY-LO-Frequency'])
    # rofreq = waveform(corder['RO-LO-Frequency'])

    for k in RJSON.keys(): corder[k] = RJSON[k] # update corder with R-parameters
    # 2b. Prepare R-waveform object for pulse-instructions
    R_waveform = {}
    for k in RJSON.keys(): R_waveform[k] = waveform(RJSON[k])
    
    # Pre-loop settings:
    # Optionals:
    # DC:
    [DC_type, DC_label] = instr['DC'].split('_')
    if "opt" not in fluxbias.data: # check if it is in optional-state / serious-state
        dcbench = module[DC_type].Initiate(current=biasmode, which=DC_label) # pending option
        module[DC_type].output(dcbench, 1)

    # SG (XY, RO):
    SG_label = [None] * len(instr['SG']) # PENDING: LISTIFY ALL INSTR.VALUES()
    [SG_type, SG_label[0]] = instr['SG'][0].split('_')
    SG0 = im("pyqum.instrument.machine.%s" %SG_type)
    if "opt" not in xyfreq.data: # check if it is in optional-state / serious-state
        sogo = SG0.Initiate(which=SG_label[0])
        SG0.power(sogo, action=['Set', str(xypowa) + ""]) # UNIT dBm NOT WORKING IN DDSLO
        SG0.rfoutput(sogo, action=['Set', 1])

    # Basics:
    # SG for RO:
    [SG_type, SG_label[1]] = instr['SG'][1].split('_')
    SG1 = im("pyqum.instrument.machine.%s" %SG_type)
    if "opt" not in rofreq.data: # check if it is in optional-state / serious-state
        saga = SG1.Initiate(which=SG_label[1])
        SG1.power(saga, action=['Set', str(ropowa) + ""]) # UNIT dBm NOT WORKING IN DDSLO
        SG1.rfoutput(saga, action=['Set', 1])

    # DAC:
    [DAC_type, DAC_label] = instr['DAC'].split('_')
    DAC = im("pyqum.instrument.machine.%s" %DAC_type)
    daca = DAC.Initiate(which=DAC_label)
    DAC.clock(daca, action=['Set', 'EFIXed',CLOCK_HZ])
    DAC.clear_waveform(daca,'all')
    DAC.alloff(daca, action=['Set',1])
    '''Prepare DAC:'''
    dt = round(1/float(DAC.clock(daca)[1]['SRATe'])/1e-9, 2)
    pulseq = pulser(dt=dt, clock_multiples=1, score="ns=%s"%ifperiod)
    pulseq.song()
    for ch in range(4):
        channel = str(ch + 1)
        DAC.prepare_DAC(daca, channel, pulseq.totalpoints, update_settings={})
    for ch in range(4):
        channel = str(ch + 1)
        DAC.compose_DAC(daca, channel, pulseq.music) # we don't need marker yet initially
    # Turn on all 4 channels:
    DAC.alloff(daca, action=['Set',0])
    DAC.ready(daca)
    DAC.play(daca)
    
    # ADC:
    [ADC_type, ADC_label] = instr['ADC'].split('_')
    ADC = im("pyqum.instrument.machine.%s" %ADC_type)
    adca = ADC.Initiate(which=ADC_label)
    '''Prepare ADC:'''
    ADC.ConfigureBoard(adca, dict(triggerDelay_sec=trigger_delay_ns*1e-9))
    TOTAL_POINTS = round(recordtime_ns / TIME_RESOLUTION_NS)

    # Buffer-size for lowest-bound data-collecting instrument:
    if readoutype == 'one-shot': # for fidelity measurement
        buffersize = recordsum * 2 # data-density of 2 due to IQ
        print("Buffer-size: %s" %buffersize)
    else: # by default we usually take average
        buffersize = TOTAL_POINTS * 2 # data-density of 2 due to IQ
        print("Buffer-size: %s" %buffersize)
    # Total data points to be saved into file:
    datasize = int(prod([waveform(corder[param]).count for param in structure], dtype='uint64')) * buffersize
    print("data size: %s" %datasize)

    # User-defined Measurement-FLOW ==============================================================================================
    
    # 1. Registerring parameter(s)-structure
    cstructure = [waveform(corder[param]).count for param in structure] # new version: separation between structure & buffer

    # 2. Start measuring:
    JOBID = g.jobidlist[0]
    job_update_perimeter(JOBID, perimeter)
    measure_loop = range(resumepoint//buffersize,datasize//buffersize) # saving chunck by chunck improves speed a lot!
    while True:
        for i in measure_loop:
            print(Back.BLUE + Fore.WHITE + 'measure single-qubit %s/%s' %(i+1,datasize//buffersize))
            # determining the index-locations for each parameters, i.e. the address at any instance
            caddress = cdatasearch(i, cstructure)
            print(Fore.BLACK + Back.WHITE + "i: %s, cstructure: %s, caddress: %s" %(i,cstructure,caddress))

            # setting each c-order (From High to Low level of execution):
            # ***************************************************************
            SCORE_DEFINED = deepcopy(SCORE_TEMPLATE)
            for j in range(len(cstructure)): # new version: all part of structure will participate
                if (not i%prod(cstructure[j+1::])) or i==resumepoint//buffersize: # virtual for-loop using exact-multiples condition
                    # print("entering %s-stage" %j)
                    # Optionals:
                    # DC
                    if structure[j] == 'Flux-Bias':
                        if "opt" not in fluxbias.data: # check if it is in optional-state
                            if biasmode: sweeprate = 0.000713  # A-mode A/s
                            else:  sweeprate = 1.37  # V-mode V/s (~10kOhm resistance)
                            module[DC_type].sweep(dcbench, str(fluxbias.data[caddress[j]]), sweeprate=sweeprate)

                    # SG
                    elif structure[j] == 'XY-LO-Frequency':
                        if "opt" not in xyfreq.data: # check if it is in optional-state
                            SG0.frequency(sogo, action=['Set', str(xyfreq.data[caddress[j]] + XY_Compensate_MHz/1e3) + "GHz"])
                    elif structure[j] == 'RO-LO-Frequency':
                        if "opt" not in rofreq.data: # check if it is in optional-state
                            SG1.frequency(saga, action=['Set', str(rofreq.data[caddress[j]] + RO_Compensate_MHz/1e3) + "GHz"])

                # DAC's SCORE-UPDATE:
                if j > 2:
                    for ch in range(4):
                        channel = str(ch + 1)
                        SCORE_DEFINED['CH%s'%channel] = SCORE_DEFINED['CH%s'%channel].replace("{%s}"%structure[j], str(R_waveform[structure[j]].data[caddress[j]]))

            # print(Fore.YELLOW + "DEFINED SCORE-CH1: %s" %(SCORE_DEFINED['CH1']))
            # IN THE FUTURE: HVI-ROUTINE STARTS HERE:
            # Basic Control (Every-loop)
            # DAC
            for ch in range(4):
                channel = str(ch + 1)
                pulseq = pulser(dt=dt, clock_multiples=1, score=SCORE_DEFINED['CH%s'%channel])
                pulseq.song()
                '''
                NOTE: 
                TKAWG's marker (number(s)) = SDAWG's markeroption
                1-4 for TKAWG: ODD-Channel for ARRA-PIN-SWITCH, EVEN-Channel for TRIGGER PURPOSE; RO-TRIGGER: MKR-1: ALZDG, MKR-2: MXA; XY-TRIGGER: MKR-1: MXA, MKR-2: SCOPE
                7 for SDAWG: PIN-Switch on MixerBox
                0 for BOTH: disabled.
                '''
                DAC.compose_DAC(daca, int(channel), pulseq.music, pulseq.envelope, 2)
            DAC.ready(daca)
            print('Waveform is Ready!')
                
            # Basic Readout (Buffer Every-loop):
            # ADC 
            DATA = ADC.AcquireData(adca, recordtime_ns*1e-9, recordsum)[0]
            # POST PROCESSING
            try:
                # TIME EVOLUTION / FIDELITY TEST:
                if readoutype == 'one-shot':
                    DATA = DATA.reshape([recordsum,TOTAL_POINTS*2])
                    if digital_homodyne != "original": 
                        for r in range(recordsum):
                            trace_I, trace_Q = DATA[r,:].reshape((TOTAL_POINTS, 2)).transpose()[0], DATA[r,:].reshape((TOTAL_POINTS, 2)).transpose()[1]
                            trace_I, trace_Q = pulse_baseband(digital_homodyne, trace_I, trace_Q, RO_Compensate_MHz, ifreqcorrection_kHz)
                            DATA[r,:] = array([trace_I, trace_Q]).reshape(2*TOTAL_POINTS) # back to interleaved IQ-Data
                            if not r%1000: print(Fore.YELLOW + "Shooting %s times" %(r+1))
                    DATA = mean(DATA.reshape([recordsum*2,TOTAL_POINTS])[:,skipoints:], axis=1)
                    print(Fore.BLUE + "DATA of size %s is ready to be saved" %len(DATA))
                else: # by default
                    DATA = mean(DATA.reshape([recordsum,TOTAL_POINTS*2]), axis=0)
                    if digital_homodyne != "original": 
                        trace_I, trace_Q = DATA.reshape((TOTAL_POINTS, 2)).transpose()[0], DATA.reshape((TOTAL_POINTS, 2)).transpose()[1]
                        trace_I, trace_Q = pulse_baseband(digital_homodyne, trace_I, trace_Q, RO_Compensate_MHz, ifreqcorrection_kHz)
                        DATA = array([trace_I, trace_Q]).transpose().reshape(TOTAL_POINTS*2) # back to interleaved IQ-Data
            
            except(ValueError):
                # raise # PENDING: UPDATE TIMSUM MISMATCH LIST
                print(Fore.RED + "Check ALZDG OPT_DMA_BUFFER!")
                break # proceed to close all & queue out
            
            # print("Operation Complete")
            print(Fore.YELLOW + "\rProgress: %.3f%%" %((i+1)/datasize*buffersize*100), end='\r', flush=True)			
            
            jobsinqueue(queue)
            if JOBID in g.jobidlist:
                # print(Fore.YELLOW + "Pushing Data into file...")
                yield list(DATA)
            else: break # proceed to close all & queue out

        # PENDING: LISTIFY / DICTIFY THE HANDLE?
        ADC.close(adca, which=ADC_label)
        DAC.alloff(daca, action=['Set',1])
        DAC.close(daca, which=DAC_label)
        if "opt" not in rofreq.data: # check if it is in optional-state
            SG1.rfoutput(saga, action=['Set', 0])
            SG1.close(saga, SG_label[1], False)
        if "opt" not in xyfreq.data: # check if it is in optional-state
            SG0.rfoutput(sogo, action=['Set', 0])
            SG0.close(sogo, SG_label[0], False)
        if "opt" not in fluxbias.data: # check if it is in optional-state
            module[DC_type].output(dcbench, 0)
            module[DC_type].close(dcbench, True, DC_label, sweeprate=sweeprate)
        if JOBID in g.jobidlist:
            qout(queue, g.jobidlist[0],g.user['username'])
        break

    return

# endregion
