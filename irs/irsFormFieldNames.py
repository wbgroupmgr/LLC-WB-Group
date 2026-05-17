'''
Build Keys & Link to LLC Ledger
- used to build <form>-keys.pdf :: each field line number should fld name
- use sequencial order -- generate per Year json file

######## Refer to end of files for IRS Form classes

'''
import os
from pathlib import Path
import json

def _fldNm(pfix,fldDict):
    return {f"{pfix}_{k}":v for k,v in fldDict.items()}

class irsFormFields(object):

    def __init__(self):
        # expand form fields with multiplier, not str value
        self.fldNmDict = self.expand(self.fldNmDict)

    def expand(self, inD):
        # Expand keys with numeric
        outD = {}
        for i,k in enumerate(inD):
            v = inD[k]
            if 'Mx' != v[0:2]: 
                outD[k] = v
                continue
            # Expand Mx key for number specified
            n = int(v[2:].split()[0])
            for i in range(n):
                outD[f"{k}_{i}"] = f"F{i}"
        return outD
                

    def __repr__(self):
        # print json version
        return json.dumps(fldNmDict, indent=4)

########. IRS FORM Section definitions

irsForm_1065_F = {
    "Hdr" : "Mx10 Top header fields",
    # --- Partnership Information ---
    "A": "Principal business activity",
    "B": "Principal product or service",
    "C": "Business code number",
    "D": "Employer identification number",
    "E": "Date business started",
    "F": "Total assets",
    "G": "Mx5",
    "Hc": "Mx3",
    "H": "Accounting method",
    "I": "Number of Schedules K-1",
    "J" : "Sch C, Sch M3 attached",
    "K" : "Mx2",

    # --- Income ---
    "1a": "Gross receipts or sales",
    "1b": "Returns and allowances",
    "1c": "Balance (1a - 1b)",
    "2": "Cost of goods sold",
    "3": "Gross profit (1c - 2)",
    "4": "Ordinary income (loss) from other partnerships",
    "5": "Net farm profit (loss)",
    "6": "Net gain (loss) from Form 4797",
    "7": "Other income (loss)",
    "8": "Total income (loss) (Sum 3-7)",

    # --- Deductions ---
    "9": "Salaries and wages (other than to partners)",
    "10": "Guaranteed payments to partners",
    "11": "Repairs and maintenance",
    "12": "Bad debts",
    "13": "Rent",
    "14": "Taxes and licenses",
    "15": "Interest",
    "16a": "Depreciation",
    "16b": "Less depreciation reported elsewhere",
    "16c": "Depreciatio Total",
    "17": "Depletion",
    "18": "Retirement plans",
    "19": "Employee benefit programs",
    "20": "Energy Deduction",
    "21": "Other deductions",
    "22": "Total deductions (Sum 9-20)",
    "23": "Ordinary business income (loss) (8 - 21)",

    # --- Tax and Payments ---
    "24": "Interest due under look-back method",
    "25": "Interest due under BBA partnership audit",
    "26": "BBA",
    "27": "Other taxes",
    "28": "Total Bal due",
    "29": "PymtElection",
    "30": "Payments (Credits, prepayments)",
    "31": "Amount owed",
    "32a": "Overpayment",
    "32b": "Mx3",
    "32c" : "Mx2",
    "32d" : "AcctNo",
    "Sign" : "Mx2",
    "PP" : "Mx7"
}



#============== mapping tables (dict) =======


irsForm_1065_Sch_B = {
    "1": "Mx6 Partnership type (General, Limited, LLC, etc.)",
    "2a": "Did any entity own 50% or more of the partnership?",
    "2b": "Did any individual or estate own 50% or more of the partnership?",
    "3a": "Did the partnership own 20% or more or 50% or more of a foreign/domestic corp?",
    "3aF" : "Mx20",
    "3b": "Did the partnership own 50% or more of a foreign/domestic partnership?",
    "3bF": "Mx20",
    "4": "File M3",
    "5": "Is the partnership a foreign partnership?",
    "6": "Number of Forms 8858 (Information Return of U.S. Persons With Respect to Foreign Disregarded Entities) attached",
    "7": "Did the partnership decrease its foreign Partners interest?",
    "8": "Is the partnership a publicly traded partnership?",
    "9": "Has the partnership filed Form 8918 (Material Advisor Disclosure)?",
    "10": "Mx10 Is the partnership under audit by the IRS?",
    "11": "Mx2 Does the partnership have foreign partners?",
    "12": "Did the partnership file Form 1042/1042-S for foreign partners?",
    "13": "Mx2 Did the partnership make passive foreign investment company (PFIC) elections?",
    "14": "Mx2 Did the partnership participate in a transaction that must be reported on Form 8886?",
    "15": "Mx2 Did the partnership receive a loan from a foreign partner?",
    "16": "Is the partnership acting as a withholding foreign partnership?",
    "17": "Does the partnership have any debt-financed acquisitions?",
    "18": "Does the partnership engage in oil and gas activities?",
    "19": "Did the partnership enter into a Section 721(c) transaction?",
    "20": "Did the partnership have any foreign branches?",
    "21": "Did the partnership make a Section 754 election?",
    "22": "Did the partnership have any taxable income from a Section 267A transaction?",
    "23": "Does the partnership have any partner that is a controlled foreign corporation (CFC)?",
    "24": "Did the partnership report any interest income on Form 1065, Line 5?",
    "25": "Number of Schedules K-1 attached (from Part III, Line 3, Schedule B-2)",
    "26": "Did the partnership pay any royalties?",
    "27": "Did the partnership have any foreign partner with a distributive share of income?",
    "28": "Did a foreign corporation acquire substantially all of the partnership's assets?",
    "29a": "Is the partnership required to file Form 7208 (Repurchase of Corporate Stock) - Foreign rules?",
    "29b": "Is the partnership required to file Form 7208 - Covered surrogate rules?"
}

irsForm_1065_Sch_K = {
        "_income_loss": "",  #---------------------------
        "1": "Ordinary business income (loss)",
        "2": "Net rental real estate income (loss)",
        "3": "Other net rental income (loss)",
        "4a": "Guaranteed payments for services",
        "4b": "Guaranteed payments for capital",
        "4c": "Total guaranteed payments",
        "5": "Interest income",
        "6a": "Ordinary dividends",
        "6b": "Qualified dividends",
        "6c": "Dividend equivalents",
        "7": "Royalties",
        "8": "Net short-term capital gain (loss)",
        "9a": "Net long-term capital gain (loss)",
        "9b": "Collectibles (28%) gain (loss)",
        "9c": "Unrecaptured section 1250 gain",
        "10": "Net section 1231 gain (loss)",
        "11": "Other income (loss)",
        "_deductions": "",  #---------------------------
        "12": "Section 179 deduction",
        "13": "Other deductions",
        "_credits": "",  #---------------------------
        "14a": "Net earnings (loss) from self-employment",
        "14b": "Gross farming or fishing income",
        "14c": "Gross nonfarm income",
        "15a": "Low-income housing credit (section 42(j)(5))",
        "15b": "Low-income housing credit (other)",
        "15c": "Qualified rehabilitation expenditures (rental real estate)",
        "15d": "Other rental real estate credits",
        "15e": "Other rental credits",
        "15f": "Undistributed capital gains credit",
        "15g": "Other credits", 
        "_foreign_transactions" : "",  #---------------------------
        "16a": "Name of country or U.S. possession", 
        "16b": "Check if Exception to Filing Sch K-2 Applies",
        "16c": "Passive category foreign source income",
        "16d": "General category foreign source income",
        "16e": "Other foreign source income",
        "16f": "Deductions allocated/apportioned - foreign branch",
        "16g": "Deductions allocated/apportioned - passive",
        "16h": "Deductions allocated/apportioned - general",
        "16i": "Deductions allocated/apportioned - other",
        "16j": "Total foreign taxes paid",
        "16k": "Total foreign taxes accrued",
        "16l": "Reduction in taxes available for credit",
        "16m": "Other foreign tax information",
        "_amt_items": "",  #---------------------------
        "17a": "Post-1986 depreciation adjustment",
        "17b": "Adjusted gain or loss",
        "17c": "Depletion (other than oil and gas)",
        "17d": "Oil, gas, and geothermal properties",
        "17e": "Other AMT items",
        "_exempt_non_deductible": "",
        "18a": "Tax-exempt interest income",
        "18b": "Other tax-exempt income",
        "18c": "Nondeductible expenses",
        "_distributions": "",  #---------------------------
        "19a": "Distributions of cash and marketable securities",
        "19b": "Distributions of other property",
        "_other_information": "",  #---------------------------
        "20a": "Investment income",
        "20b": "Investment expenses",
        "20c": "Other items and amounts"
    }

irsForm_1065_Sch_L = {
        "ANI_1" : "Net Income",
        "ANI" : "Mx12 breakdown by member",
        "1": "Mx4 Cash",
        "2a": "Mx4 Trade notes and accounts receivable",
        "2b": "Mx4 Less allowance for bad debts",
        "3": "Mx4 Inventories",
        "4": "Mx4 U.S. government obligations",
        "5": "Mx4 Tax-exempt securities",
        "6a": "Mx4 Other current assets (attach statement)",
        "7": "Mx4 Mortgage and real estate loans",
        "8": "Mx4 Other investments (attach statement)",
        "9a": "Mx4 Buildings and other depreciable assets",
        "9b": "Mx4 Less accumulated depreciation",
        "10a": "Mx4 Depletable assets",
        "10b": "Mx4 Less accumulated depletion",
        "11": "Mx4 Land (net of any amortization)",
        "12a": "Mx4 Intangible assets (amortizable only)",
        "12b": "Mx4 Less accumulated amortization",
        "13": "Mx4 Other assets (attach statement)",
        "14": "Mx4 Total assets",
        "15": "Mx4 Accounts payable",
        "16": "Mx4 Mortgages, notes, bonds payable in less than 1 year",
        "17": "Mx4 Other current liabilities (attach statement)",
        "18": "Mx4 All nonrecourse loans",
        "19a": "Mx4 Mortgages, notes, bonds payable in 1 year or more",
        "19b": "Mx4 Less mortgages/notes payable in less than 1 year",
        "20": "Mx4 Other liabilities (attach statement)",
        "21": "Mx4 Partners' capital accounts",
        "22": "Mx4 Total liabilities and capital"
}

irsForm_1065_Sch_M1 = {
    "1": "Net income (loss) per books",
    "2": "Income included on Schedule K, lines 1, 2, 3c, 5, 6a, 7, 8, 9a, 10, and 11, not recorded on books this year",
    "3": "Guaranteed payments (other than late interest) (line 4c)",
    "4a": "Depreciation",
    "4b": "Travel and entertainment",
    "4": "Expenses recorded on books this year not included on Schedule K, lines 1 through 13e, and 16p (itemize):",
    "4c": "Other (list)",
    "5": "Add lines 1 through 4",
    "6": "Income recorded on books this year not included on Schedule K, lines 1 through 13e, and 16p (itemize):",
    "6a": "Tax-exempt interest",
    "6b": "Other (list)",
    "6": "Income recorded on books this year not included on Schedule K, lines 1 through 13e, and 16p (itemize):",
    "7a": "Depreciation",
    "7b": "Other (list)",
    "7": "Deductions included on Schedule K, lines 1 through 13e, and 16p, not charged against book income this year (itemize):",
    "8": "Add lines 6 and 7",
    "9": "Income (loss) (Analysis of Net Income (Loss) per Return, line 1). Line 5 minus line 8"
}

irsForm_1065_Sch_M2 = {
    "1": "Balance at beginning of year",
    "2a": "Capital contributed: Cash",
    "2b": "Capital contributed: Property",
    "3": "Net income (loss) per books (or tax basis)",
    "4": "Mx2 Other increases (itemize)",
    "5": "Add lines 1 through 4",
    "6a": "Distributions: Cash",
    "6b": "Distributions: Property",
    "7": "Mx2 Other decreases (itemize)",
    "8": "Add lines 6a, 6b, and 7",
    "9": "Balance at end of year (line 5 less line 8)"
}


irsForm_K1_PI = {
    "Hdr" : "Mx7 Header fields",
    "A": "Partnership's employer identification number (EIN)",
    "B": "Partnership's name, address, city, state, and ZIP code",
    "C": "IRS center where partnership filed return",
    "D": "Publicly traded partnership (PTP) checkbox"
}

irsForm_K1_PII = {
    "E": "Partner SSN/TIN",
    "F": "Partner Name, Address, City, State, ZIP",
    "G": "Mx2 General partner/LLC member-manager or Limited partner",
    "H1": "Mx2 DomesticForeign",
    "H2": "Mx3 DisregardedEntity",
    "I1": "EntityType",
    "I2": "RetirementPlan",
    "J_P": "Mx2 Partners share Profits (Beg/End)",
    "J_J": "Mx2 Partners share Loss",
    "J_Cap": "Mx2 Partners share Capital",
    "J_Ck": "Mx2 Partners share",
    "K1_Nr": "Mx2 Partners share of Nonrecourse Liabilities (Beginning)",
    "K1_QNr": "Mx2 Partners Qualified Nonrecourse",
    "K1_R": "Partners share Recourse",
    "K2" : "Liability",
    "K3" : "Guarntees/Obligations",
    "L_Beg" : "Cap Account",
    "L_CapContrib": "Capital Contributed during the year",
    "L_CInc": "Current Year Increase (Decrease)",
    "L_Other": "Other Increases",
    "L_Wdwl": "Withdrawals & Distributions",
    "L_EndCao": "Partners Capital Account (Ending)",
    "M": "Mx2 Did the partner contribute property with a built-in gain/loss?",
    "N": "Mx2 Partners share of net unrecognized Section 704(c) gain/loss"
}

irsForm_K1_PIII = {
    "1": "Ordinary business income (loss)",
    "2": "Net rental real estate income (loss)",
    "3": "Other net rental income (loss)",
    "4a": "Guaranteed payments for services",
    "4b": "Guaranteed payments for capital",
    "4c": "Total guaranteed payments",
    "5": "Interest income",
    "6a": "Ordinary dividends",
    "6b": "Qualified dividends",
    "6c": "Dividend equivalents",
    "7": "Royalties",
    "8": "Net short-term capital gain (loss)",
    "9a": "Net long-term capital gain (loss)",
    "9b": "Collectibles (28%) gain (loss)",
    "9c": "Unrecaptured section 1250 gain",
    "10": "Net section 1231 gain (loss)",
    "11": "Mx4 Other income (loss)",
    "12": "Section 179 deduction",
    "13": "Mx6 Other deductions",
    "14": "Mx4 Self-employment earnings (loss)",
    "15": "Mx4 Credits",
    "16": "Schedule K-3 is attached if checked",
    "17": "Mx6 Alternative minimum tax (AMT) items",
    "18": "Mx6 Tax-exempt income and nondeductible expenses",
    "19": "Mx4 Distributions",
    "20": "Mx8 Other information",
    "21": "Foreign taxes paid or accrued",
    "22": "More than one activity for at-risk purposes",
    "23": "More than one activity for passive activity purposes"
}

########. Form Fields Classes

class irsF1065Fields(irsFormFields):
    fldNmDict = (_fldNm('P1',irsForm_1065_F) |
                _fldNm('B',irsForm_1065_Sch_B) |
                _fldNm('K',irsForm_1065_Sch_K) |
                _fldNm('L',irsForm_1065_Sch_L) |
                _fldNm('M1',irsForm_1065_Sch_M1) |
                _fldNm('M2',irsForm_1065_Sch_M2)
                )
                         

class irsSchKFields(irsFormFields):
    fldNmDict = (_fldNm('P1',irsForm_K1_PI) |
                _fldNm('P2',irsForm_K1_PII) |
                _fldNm('P3',irsForm_K1_PIII)
                )
                        
