import argparse
from uillc.llcMgmt import llcMgmt
from util.utilEditSession import utilEditSession




def main():
    parser = argparse.ArgumentParser(description="Start LLC Management Flask app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--notebook", action="store_true")
    
    # Add the 'load' flag. If present, it becomes True.
    parser.add_argument('--load', action='store_true', help="Set to True to load existing data (default: False)")
    parser.add_argument('--edOpt', type=str, default='llc',  help="editor option: llc| llcAsset | llcExpRev;  (default=llc) " )
    parser.add_argument('--llcName', type=str, default='NoNameLLC',  help="LLC Name,  e.g.'WidgersLLC'" )
   
    args = parser.parse_args()
    nb = args.notebook
    
    print("============ EditSession - Initialize")
    eSession = utilEditSession(llcName=args.llcName, load = args.load, edOpt=args.edOpt)
    print(eSession, llcMgmt)
    
    print(f"\n\n============ FLASK App start NB:{nb}")

    app = llcMgmt(eSession)

    if False:
        # ORIGIONAL 
        app = LLCManagementApp(
            assets_path=args.assets,
            exprev_path=args.expRev
        )
    app.run(host=args.host, port=args.port, debug=args.debug, notebook=nb)


if __name__ == "__main__":
    main()
