# Communicating with Modular DDS-LO (QES2) M9347A (Latest:2020/12)
from colorama import init, Fore, Back
init(autoreset=True) #to convert termcolor to wins color

from os.path import basename as bs
mdlname = bs(__file__).split('.')[0] # module's name e.g. PSG

import pyvisa as visa
from pyqum.instrument.logger import address, set_status, status_code, debug
from pyqum.instrument.logger import translate_scpi as Attribute

debugger = debug(mdlname)

# INITIALIZATION
def Initiate(which, mode='DATABASE'):
    ad = address(mode)
    rs = ad.lookup(mdlname, label=int(which)) # Instrument's Address
    rm = visa.ResourceManager()
    try:
        card = rm.open_resource(rs) #establishing connection using GPIB# with the machine
        stat = [1,1] # card.write('*CLS') #Clear buffer memory; Load preset
        card.read_termination = '\n' #omit termination tag from output 
        card.timeout = 150000 #set timeout in ms
        # Default Configurations:
        clock_source(card, action=['Set_', 'REFIN100MHZ'])
        clock_align(card)
        print(Fore.GREEN + "Clock aligned: %s" % (clock_source(card)[1]['SOURCE']))
        # Logging:
        set_status(mdlname, dict(state='connected'), which)
        print(Fore.GREEN + "%s-%s's connection Initialized: %s" % (mdlname,which, str(stat)))
        ad.update_machine(1, "%s_%s"%(mdlname,which))
    except: 
        # raise
        set_status(mdlname, dict(state='DISCONNECTED'), which)
        print(Fore.RED + "%s-%s's connection NOT FOUND" %(mdlname,which))
        # card = "disconnected"
    return card

@Attribute
def model(card, action=['Get', '']):
    SCPIcore = '*IDN'  #inquiring machine identity: "who r u?"
    return mdlname, card, SCPIcore, action


@Attribute
def frequency(card, action=['Get', '']):
    '''This command sets the RF output frequency of the synthesizer.
        [:DDS[1]|2]:FREQuency <val>[<unit>] ex. :DDS1:FREQ 6GHZ
        action=['Set','6GHz']'''
    SCPIcore = ':DDS:FREQUENCY' 
    return mdlname, card, SCPIcore, action


@Attribute
def power(card, action=['Get', '']):
    '''This command sets the RF output power of the synthesizer.
        The query returns the maximum or minimum allowable power level if the optional MAXimum or MINimum are used.
        [:DDS[1]|2]:POWer <val> (unit will cause illusional error!!!)
        [:DDS[1]|2]:POWer? [MAXimum|MINimum] => EX: ['Get','MAX']
    '''
    SCPIcore = ':DDS:POWER'
    return mdlname, card, SCPIcore, action

@Attribute
def phase(card, action=['Get', '']):
    '''This command applies a phase rotation, in degrees, to the data generated by the
        synthesizer.
        [:DDS[1]|2]:PHASe <val>
        ex. :DDS2:PHAS -45 The preceding example applies a -45° phase rotation to synthesizer channel #2
        action=['Set','-45']'''
    SCPIcore = ':DDS:PHASE'
    return mdlname, card, SCPIcore, action

@Attribute
def rfoutput(card, action=['Get', '']):
    '''This command enables or disables the RF output of the synthesizer.
        [:DDS[1]|2]:OUTPut[:STATe] ON|OFF|1|0 
        ex. :DDS2:OUTP OFF The preceding example disables the RF output of synthesizer channel #2.
        action=['Set','OFF']'''
    SCPIcore = ':DDS:OUTPUT:STATE'
    return mdlname, card, SCPIcore, action


@Attribute
def clock_align(card, action=['Set', ' ']):
    '''SET ONLY!
    This command invokes an internal alignment to lock the DDS chips to the system clock. 
    This alignment must be performed whenever the system clock source is changed.
    '''
    SCPIcore = ':CAL:SCLK' 
    return mdlname, card, SCPIcore, action

@Attribute
def clock_source(card, action=['Get', '']):
    '''This command sets the source of the system clock.  
    The M9347A supports three different methods for providing a system clock:  A direct clock from 17-20.0 GHz, a direct clock at 4.8 GHz, or a 100 MHz reference clock.  
    The direct clock must be provided at the Clock In port of the front panel, and the 100 MHz must be provided at the Ref In port of the front panel.
    OPTION:  CLKIN| CLKIN4800MHZ| REFIN100MHZ
    '''
    SCPIcore = ':CLK:SOURCE' 
    return mdlname, card, SCPIcore, action

@Attribute
def clock_frequency_out(card, action=['Get', '']):
    '''This command sets the frequency at the Ref Out port of the front panel. 
        The available choices are dependent upon the clock source. 
        The following table describes the possible OPTIONs:
        Clock SOURce            Reference Out Frequency
        Direct In (17-20 GHz)   REFOUT19200MHZ, OFF
        Clock In 4.8 GHz        REFOUT19200MHZ, REFOUT4800MHZ, OFF
        Ref In 100 Mhz          REFOUT19200MHZ, REFOUT4800MHZ, REFOUT100MHZ, OFF
        '''
    SCPIcore = ':CLK:REFerence:OUT:FREQuency'
    return mdlname, card, SCPIcore, action


def close(card, which, reset=True, mode='DATABASE'):
    if reset:
        card.write('*RST') # reset to factory setting (including switch-off)
        set_status(mdlname, dict(config='reset'), which)
    else: set_status(mdlname, dict(config='previous'), which)
    try:
        card.close() #None means Success?
        status = "Success"
        ad = address(mode)
        ad.update_machine(0, "%s_%s"%(mdlname,which))
    except: 
        status = "Error"
    set_status(mdlname, dict(state='disconnected with %s' %status), which)
    print(Back.WHITE + Fore.BLACK + "%s's connection Closed with %s" %(mdlname,status))
    return status
        

# Test Zone by PYQUMAPP:
def test(card, detail=True):
    S={}
    S['x'] = card
    s = S['x']
    if s is "disconnected":
        pass
    else:
        if debug(mdlname, detail):
            print(Fore.RED + "Detailed Test:")
            

        else: print(Fore.RED + "Basic IO Test")
    # if not bool(input("Press ENTER (OTHER KEY) to (skip) reset: ")):
    #     state = True
    # else: state = False
    # close(s, reset=state)
    return 'Success'

# ON-SITE TESTING:
def onsitest():
    from time import sleep
    debug(mdlname, True)
    c = Initiate(1, mode='TEST')
    model(c)
    clock_source(c, action=['Get_', ''])
    clock_source(c, action=['Set_', 'REFIN100MHZ'])
    clock_source(c, action=['Get_', ''])
    clock_frequency_out(c)

    # NOTE: Default Channel = 1
    for ch in ['']:
        frequency(c,action=['Get_%s'%ch, ''])
        frequency(c,action=['Set_%s'%ch, '4.95GHZ'])
        frequency(c,action=['Get_%s'%ch, ''])

        print("MAX POWER: %s" %power(c,['Get_%s'%ch,'MAX'])[1]['POWER'])

        phase(c,action=['Get_%s'%ch,''])
        phase(c,action=['Set_%s'%ch,'0.137'])
        phase(c,action=['Get_%s'%ch,''])

        rfoutput(c,action=['Get_%s'%ch,''])
        rfoutput(c,action=['Set_%s'%ch,'1'])
        rfoutput(c,action=['Get_%s'%ch,''])

        for pow in [-30, 0]: #, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12]:
            power(c,action=['Get_%s'%ch,''])
            power(c,action=['Set_%s'%ch,'%s'%pow]) # MISLEADING MANUAL: UNIT DBM/dBm DOESN'T WORK IN SCPI COMMAND
            power(c,action=['Get_%s'%ch,''])
            sleep(7)

        sleep(7)

    close(c,1,reset=True, mode='TEST')    
    return

# onsitest()
