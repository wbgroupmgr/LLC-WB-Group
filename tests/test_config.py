import json; from pathlib import Path
cfg = json.loads((Path.home()/'.llcRentalTracker/config.json').read_text())

# APP_SECRET_KEY is at top level (per-tracker)
print('APP_SECRET_KEY:', 'SET' if cfg.get('APP_SECRET_KEY') else 'MISSING')

# APP_GPG_PASSPHRASE is in each llcList stanza (per-BUS)
stanza = cfg['llcList'][0]
print('APP_GPG_PP    :', 'SET' if stanza.get('APP_GPG_PASSPHRASE') else 'MISSING')

# Stale keys that should be absent
print('LLC_ stale    :', 'STALE — REMOVE' if cfg.get('secrets', {}).get('LLC_GPG_PASSPHRASE') else 'absent ✓')
print('master_pp     :', 'PRESENT — REMOVE' if 'master_passphrase' in cfg else 'absent ✓')

print('llcName       :', stanza.get('llcName'))
print('years         :', stanza.get('years'))
print('bus_repo ok   :', Path(stanza['bus_repo']).exists())
