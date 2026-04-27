- 2026.04.23 - 23:00 - New session / wkL 0%,  wkR: None,  sL: 0%, sR: None
- 2026.04.24 - 01:00 - 10 tasks / wkL 17%,  wkR: 1:00:00, sL:27% ,sR: 02:20:00
````
Review and enhance as needed the following 

irs/docs folder for design, program flows and data flows. 
1. Make no changes to these docs
2. Take special notice of irsForm1065_book / irsDesign.md and the following files:
    1. ui.llcIRSViewBase.py -- Abstract base/mixin — loads IS/BS/owners data
    2. ui.llcForm1065.py - Concrete view — row table for Form 1065, Page
3. These modules violate the Architecture Guide that all data manipulation rules. Thus the construction of profile object for IRS consumption should be in the ledger services. Thus I created the ledger.llcProfile for encapulating the LLC profile data needed for IRS forms 1065, e.g. business name, etc...
4. The ui.llcIRSViewBase.py -- should be deleted and data should be retrieved from ledger.stmtProfile.
5. refractor ui.llcForm1065 to utilize ledger.stmtProfile
6. ledger.stmtProfile - I implemented the basic constructor to import the llc.entity and llc.F1065 data. -- this creates a table where the convention is to give it an acct name 'Profile.entity.FieldName / Profile.F1065.FieldName... and lineNo is the order within eac of these dicts. --- review and sanitize the code so it behaves like a ledger.stmt object.
7. It is not clear we have achieved the goals of ProjectLevel3 v0.2... assess whether all data constructions/load/saving/wrangling is performed by ledger services.
8. I want to change the IRS tax views -- move the separate views for Form1065 pg2-6 from separate views into collapsable frames in the Form1065 view. So one can see the WHOLE 1065 form with a single view.
9. Note that the 1065 does not have the headers information at top of Page1
10. Please add a data flow diagram for Form 1065 according to the Book to IRS PDF workflow.
````
- 2026.04.24 - 8:53 Do #56 - generate dataflow .md file / wkL 21%,  wkR: 1:00:00 sessionL:27% sR: 02:20:00
- 2026.04.24 - 8:53 log #53 into a future task "Cleanup Code" / wkL 21%,  wkR: 1:00:00 sessionL:27% sR: 02:20:00