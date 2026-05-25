# Aerogor Writable Parameters

Complete list of writable parameters extracted from the `myheatpump.com` cloud GUI.

**Conversion:** `local_protocol_byte = cloud_par_number - 1`

To write a parameter locally, send a 22-byte write command (see protocol-reference.md) with the parameter byte set to the value below and the float value within the range shown.

| Cloud | Local byte | Parameter | Type | Range / Options |
|---|---|---|---|---|
| par1 | `0x00` | Unit ON OFF | enum | 0=OFF; 1=ON |
| par2 | `0x01` | Software Version No. | number | 0..1000 |
| par3 | `0x02` | Database Version | number | 0..100 |
| par4 | `0x03` | Working Mode | enum | 0=Standby; 1=Heating; 2=Cooling; 3=Sanitary Hot Water; 4=Auto |
| par5 | `0x04` | Language | enum | 0=English; 1=Slovenščina; 2=Deutsch; 3=Polski; 4=Italiano; 5=Русский; 6=Українська; 7=Polski; 8=English; 9=English; 10=English; 11=English; 12=English; 13=English; 14=English; 15=中文 |
| par6 | `0x05` | Sanitary Hot Water | enum | 0=OFF; 1=ON |
| par7 | `0x06` | Heating | enum | 0=OFF; 1=ON |
| par8 | `0x07` | Cooling | enum | 0=OFF; 1=ON |
| par9 | `0x08` | Cooling and Heating Switch | enum | 0=Invalid; 1=Ambient Temp.; 2=External Signal Control; 3=External Signal Control+Ambient Temp. |
| par10 | `0x09` | Basic Operation Modes | enum | 0=OFF; 1=ON |
| par11 | `0x0A` | Ambient Temp. To Start Heating | number | -10..25 |
| par12 | `0x0B` | Ambient Temp. To Start Cooling | number | 8..53 |
| par13 | `0x0C` | Max Allowed Duration For Min Compressor Speed | number | 5..60 |
| par19 | `0x12` | Heating/Cooling ON/OFF Timer | enum | 0=OFF; 1=ON |
| par20 | `0x13` | Heating/Cooling Stops Based on Water ∆T | number | 1..3 |
| par21 | `0x14` | Heating/Cooling Restarts Based on Water ∆T | number | 1..10 |
| par22 | `0x15` | ∆T Compressor Speed-reduction | number | 1..10 |
| par23 | `0x16` | Set temp. for Cooling | number | 0..100 |
| par24 | `0x17` | Heating Curve | enum | 0=OFF; 1=ON |
| par25 | `0x18` | Ambient Temp. 1 | number | -25..35 |
| par26 | `0x19` | Ambient Temp. 2 | number | -25..35 |
| par27 | `0x1A` | Ambient Temp. 3 | number | -25..35 |
| par28 | `0x1B` | Ambient Temp. 4 | number | -25..35 |
| par29 | `0x1C` | Ambient Temp. 5 | number | -25..35 |
| par30 | `0x1D` | Water Temp. A /Ambient Temp. 1 | number | 20..60 |
| par31 | `0x1E` | Water Temp. B/Ambient Temp. 2 | number | 20..60 |
| par32 | `0x1F` | Water Temp. C/Ambient Temp. 3 | number | 20..60 |
| par33 | `0x20` | Water Temp. D/Ambient Temp .4 | number | 20..60 |
| par34 | `0x21` | Water Temp. E/Ambient Temp. 5 | number | 20..60 |
| par35 | `0x22` | Room temp. effect on Heating Curve | enum | 0=OFF; 1=ON |
| par36 | `0x23` | Ideal Room temp. in Heating | number | 15..35 |
| par37 | `0x24` | Ideal Room temp. in Cooling | number | 15..35 |
| par38 | `0x25` | Set temp. for Heating (without heating curve) | number | 20..60 |
| par39 | `0x26` | Low Temperature Limit | number | 7..60 |
| par40 | `0x27` | High Temperature Limit | number | 7..75 |
| par41 | `0x28` | Anti-Legionella Program | enum | 0=OFF; 1=ON |
| par42 | `0x29` | Setpoint | number | 60..80 |
| par43 | `0x2A` | Duration | number | 5..60 |
| par44 | `0x2B` | Finish Time | number | 10..180 |
| par45 | `0x2C` | Vacation Mode | enum | 0=OFF; 1=ON |
| par46 | `0x2D` | Sanitary Hot Water temp. Drop during Vacation Mode | number | 10..50 |
| par47 | `0x2E` | Heating Water temp. Drop during Vacation Mode | number | 10..50 |
| par48 | `0x2F` | Backup Heating Sources For Heating | enum | 0=OFF; 1=ON |
| par49 | `0x30` | Priority for Backup Heating Sources (HBH) | enum | 0=Lower than AH; 1=Higher than AH |
| par50 | `0x31` | Backup Heating Source for Sanitary Hot Water | enum | 0=OFF; 1=ON |
| par51 | `0x32` | Priority for Backup Heating Sources (HWTBH) | enum | 0=Lower than AH; 1=Higher than AH |
| par52 | `0x33` | Heating Source Start Accumulating Value (HBH) | number | 5..600 |
| par53 | `0x34` | Water Temperature Rise Reading Interval (HWTBH) | number | 5..60 |
| par54 | `0x35` | Emergency Operation | enum | 0=OFF; 1=ON |
| par55 | `0x36` | Setpoint DHW | number | 25..75 |
| par56 | `0x37` | DHW Restart ∆T Setting | number | 2..15 |
| par57 | `0x38` | Shifting Priority | enum | 0=OFF; 1=ON |
| par58 | `0x39` | Shifting Priority Stating Temp. | number | -15..20 |
| par59 | `0x3A` | Sanitary Water Min. Working Hours | number | 10..60 |
| par60 | `0x3B` | Heating Max. Working Hours | number | 30..180 |
| par61 | `0x3C` | Allowable temp Drift in Heating | number | 3..10 |
| par62 | `0x3D` | DHW Backup Heater for Shifting Priority | enum | 0=OFF; 1=ON |
| par63 | `0x3E` | Sanitary Hot Water Storage Function | enum | 0=OFF; 1=ON |
| par64 | `0x3F` | Reheating Function | enum | 0=OFF; 1=ON |
| par65 | `0x40` | Reheating Set Temp. | number | 25..55 |
| par66 | `0x41` | Reheating Restart ∆T Setting | number | 2..20 |
| par67 | `0x42` | Heating&cooling Circuit 2 | enum | 0=OFF; 1=ON |
| par68 | `0x43` | Set temp. For Cooling | number | 0..100 |
| par69 | `0x44` | Heating Curve | enum | 0=OFF; 1=ON |
| par70 | `0x45` | Water Temp. A/Ambient Temp. 1 | number | -666..666 |
| par71 | `0x46` | Water Temp. B/Ambient Temp. 2 | number | -666..666 |
| par72 | `0x47` | Water Temp. C/Ambient Temp. 3 | number | -666..666 |
| par73 | `0x48` | Water Temp. D/Ambient Temp .4 | number | -666..666 |
| par74 | `0x49` | Water Temp. E/Ambient Temp. 5 | number | -666..666 |
| par75 | `0x4A` | Set Temp. for Heating (without heating curve) | number | 0..100 |
| par76 | `0x4B` | High Temperature Limit | number | 7..75 |
| par77 | `0x4C` | Low Temperature Limit | number | 7..60 |
| par78 | `0x4D` | Reduced Setpoint | enum | 0=OFF; 1=ON |
| par79 | `0x4E` | Temp. Drop/Rise | number | 2..10 |
| par80 | `0x4F` | Quiet Operation | enum | 0=OFF; 1=ON |
| par81 | `0x50` | Allowable Temp. Drifting | number | 2..10 |
| par82 | `0x51` | Operation Signal for Electrical Utility Lock | enum | 0=Normally Close; 1=Normally Open |
| par83 | `0x52` | Electrical Utility Lock | enum | 0=OFF; 1=ON |
| par84 | `0x53` | HBH During Electrical Utility Lock | enum | 0=OFF; 1=ON |
| par85 | `0x54` | P0 during Electrical Utility Lock | enum | 0=OFF; 1=ON |
| par86 | `0x55` | Control Panel Backlight Light | enum | 0=Allways ON; 1=3 min.; 2=5 min.; 3=10 min. |
| par87 | `0x56` | Circulation Pump P0 Type | enum | 0=DC Variable Speed Pump（PWM control）; 1=AC Pump |
| par88 | `0x57` | Speed Setting of Circulation Pump P0 | enum | 0=High Speed; 1=Medium Speed; 2=Low Speed |
| par89 | `0x58` | Working Mode of Circulation Pump P0 | enum | 0=Interval working mode; 1=ON Constatntly; 2=OFF with Compressor |
| par90 | `0x59` | Pump Off Interval for P0 | number | 5..60 |
| par91 | `0x5A` | Pump On Time for P0 | number | 1..10 |
| par92 | `0x5B` | Buffer Tank | enum | 0=OFF; 1=ON |
| par93 | `0x5C` | Mixing Valve | enum | 0=OFF; 1=ON |
| par94 | `0x5D` | Mixing Valve | enum | 0=OFF; 1=ON |
| par95 | `0x5E` | P1 for Heating Operation | enum | 0=OFF; 1=ON |
| par96 | `0x5F` | P1 for Cooling Operation | enum | 0=OFF; 1=ON |
| par97 | `0x60` | P1 with High Temp. Demand | enum | 0=OFF; 1=ON |
| par98 | `0x61` | P2 for Heating Operation | enum | 0=OFF; 1=ON |
| par99 | `0x62` | P2 for Cooling Operation | enum | 0=OFF; 1=ON |
| par100 | `0x63` | P2 with High Temp. Demand | enum | 0=OFF; 1=ON |
| par101 | `0x64` | Floor Curing | enum | 0=OFF; 1=ON |
| par102 | `0x65` | Floor Curing Current Stage | number | 0..16 |
| par103 | `0x66` | Floor Curing Current Stage Running Duration | number | -50..500 |
| par104 | `0x67` | Floor Curing Current Stage Set Temperature | number | 0..100 |
| par105 | `0x68` | Floor Curing Current Stage Valid Running Duration | number | 0..100 |
| par106 | `0x69` | Floor Curing Total Running Duration | number | 0..100 |
| par107 | `0x6A` | Highest Water Temp. in Floor Curing Operation | number | 0..100 |
| par108 | `0x6B` | Ambient Temp. to Activate First Class Anti-freezing | number | 5..10 |
| par109 | `0x6C` | Ambient Temp. to Activate Second Class Anti-freezing | number | 0..4 |
| par110 | `0x6D` | Ambient Temp. to Stop Second Class Anti-freezing | number | 0..10 |
| par111 | `0x6E` | Water Temp. to Activate Second Class Anti-freezing | number | 5..30 |
| par112 | `0x6F` | Water Temp. to Stop Second Class Anti-freezing | number | 5..30 |
| par114 | `0x71` | Mode Switch during Defrosting | enum | 0=OFF; 1=ON |
| par116 | `0x73` | Motorized Diverting Valve switching time | number | 0..16 |
| par117 | `0x74` | Power On Time for Motorized Diverting Valve | number | 0..16 |
| par118 | `0x75` | Fan Speed Limit | number | 90..100 |
| par119 | `0x76` | Mode Signal Output | enum | 0=No Output; 1=Heating; 2=Cooling |
| par120 | `0x77` | Mode Signal Type | enum | 0=Normally Close; 1=Normally Open |
| par121 | `0x78` | Curve 1 Parallel Move | number | -3..3 |
| par122 | `0x79` | Curve 2 Parallel Move | number | -3..3 |
| par124 | `0x7B` | DHW ECO Function | enum | 0=OFF; 1=ON |
| par125 | `0x7C` | DHW ECO Starting Ambient Temp. | number | -20..43 |
| par126 | `0x7D` | Heating ECO Operation | enum | 0=OFF; 1=ON |
| par127 | `0x7E` | Ambient Temp. to Start Heating ECO Operation | number | -20..433 |
| par128 | `0x7F` | Tw Sensor Dropped From its Position | enum | 0=OFF; 1=ON |
| par129 | `0x80` | Signal for Cutting Outdoor Unit Power Supply | enum | 0=OFF; 1=ON |
| par130 | `0x81` | Ambient Temp. to Stop Cutting Outdoor Unit Power Supply | number | -5..25 |
| par131 | `0x82` | Speed setting of Circulation Pump in Heating Operation | enum | 0=High Speed; 1=Medium Speed; 2=Low Speed |
| par132 | `0x83` | Speed setting of Circulation Pump in Coolting Operation | enum | 0=High Speed; 1=Medium Speed; 2=Low Speed |
| par133 | `0x84` | Speed setting of Circulation Pump in DHW Operation | enum | 0=High Speed; 1=Medium Speed; 2=Low Speed |
| par134 | `0x85` | Block the Working of Auxiliary Heater (AH) | enum | 0=OFF; 1=ON |
| par135 | `0x86` | Block the Working of Auxiliary Heater (AH) According to Ambient Temp. | enum | 0=OFF; 1=ON |
| par136 | `0x87` | Set Ambient Temp. to Block the Working of Auxiliary Heater | number | -20..30 |
| par137 | `0x88` | HeatPump PCB Software Version No. | number | 0..1000000 |
| par138 | `0x89` | Outdoor PCB EEPROM Version | number | 0..1000000 |
| par190 | `0xBD` |  | number | 0..1 |
