from eaps2000 import eaps2k

port = "COM6"
with eaps2k(port=port) as ps:
    cfg=eaps2k.get_config_template()
    cfg['ACK'] = True  # acknowledge alarms if any
    cfg['OVP'] = 5.0   # over-voltage-protection value
    # cfg['OCP'] = 0.5   # over-current-protection value
    # cfg['Iset'] = 0.1  # current to be set
    # cfg['Vset'] = 3.3  # voltage to be set

    # Turn off the output stage:
    # ps.set_output_state(False)

    # Apply configuration:
    ps.configure(cfg)

    # Turn on the output stage:
    # ATTENTION: The power will be applied to your probe here!

    # ps.set_output_state(True)

    # Show information:
    ps.print_info()