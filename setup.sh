#!bash

set -x
rm ~/.llcRentalTracker/*.json
python3 wsCmd.py --newBus /Users/frankrojas/GDrive/Family/Assets/LLC-WBGroup --year 2025 --llcName WBGroupLLC
echo "--------"
cat ~/.llcRentalTracker/config.json
echo "--------"
python3 wsCmd.py --setup --llcName WBGroupLLC
echo "--------"
cat ~/.llcRentalTracker/config.json
echo "--------"
