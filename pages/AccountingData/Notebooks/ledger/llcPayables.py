'''
manage A/P




'''
import os
import pandas as pd
import datetime

from ledger.ledgerDB import ledgerDB


# class llcPayables
class llcPayables(ledgerDB):
    def __init__(self, llc, **kwargs):
        super().__init__(llc, **kwargs)
        self.md = mdIRS # Display Tios/Guidelines
        if self.debug: print(f"llc:{self.oID} {type(self).__name__} Init Done")
            
    def FN(self): 
        fn = os.path.join(self.llc.TOP, self.llc.dirAccounting, 'Accts', f"{self.oID}_{self.llc.objName}.json")
        if self.debug: print(f"{self.oID} ledgerObject.FN: {fn}")
        return fn

    """
    -----------------------------------------------
    Services for classification and reconcilation
    - call .fetch() before using services
    -----------------------------------------------
    None
    """
    
        
mdIRS = '''
<h2> Account Payables 
Added to manage member purchases outside of Bank and need reimbursements
'''
