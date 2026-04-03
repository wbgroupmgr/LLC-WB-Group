# class llcOwners
'''
manage owners of LLC
list of owners is stored in accountingData/YEAR/llcOwners_<llcName>.json
'''

mdIRS = '''

## Self-Employment Taxes 
- members of a multi-member LLC (typically taxed as a partnership) 
- generally must declare their share of profits as self-employment income. 
- members are responsible for self-employment tax (social security and medicare) 
    - on your portion of the net earnings
    - usually reported on Schedule SE of your personal 1040 tax return. 

### Key Takeaways for Multi-Member LLCs
- **Tax Classification**: The IRS treats multi-member LLCs as partnerships by default, meaning profits "pass-through" to members.
- **Self-Employment Tax**: Active members generally pay self-employment tax on their share of ordinary business income, as they are not considered employees.
- **Reporting**: 
    - The LLC files Form 1065 (Partnership Return), 
    - Each member receives a Schedule K-1, which reports their share of income, deductions, and credits.
- **Threshold**: 
    - You usually must pay self-employment tax if your net earnings are $400 or more. 

### Important Considerations
- **Guaranteed Payments**: Payments for services rendered to the LLC, regardless of profit, are generally subject to self-employment tax.
- **Passive Members**: Passive investors (like limited partners) might not owe self-employment tax on their share of income, though this is a complex area.
- **S-Corp Election**: If the LLC elects to be taxed as an S-Corporation, active members may be treated as employees, allowing them to pay self-employment tax only on a reasonable salary, not on total profits.
'''

import os
from ledger.ledgerObject import ledgerObject

class llcOwners(ledgerObject):
    def __init__(self, llc, **kwargs):
        super().__init__(llc, **kwargs)
        if self.debug: print(f"llc:{self.oID} {type(self).__name__} Init Done")

    def FN(self): 
        fn = os.path.join(self.llc.TOP, self.llc.dirAccounting, 'Accts', f"{self.oID}_{self.llc.objName}.json")
        if self.debug: print(f"{self.oID} ledgerObject.FN: {fn}")
        return fn

        
