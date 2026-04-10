# Transaction Editor - Command Line Usage Guide

THIS GUIDE NEEDS EDITING TO SYNC WITH CHANGES

## 📋 Prerequisites

1. **Python 3.7+** installed
2. **Flask** installed: `pip install flask`
3. **Files in your project directory:**
   - `transaction_editor.py` - The TransactionEditor class
   - `main.py` - Command line runner
   - `llcAssets_WBGroupLLC.json` - Your assets file
   - `llcExpRev_WBGroupLLC.json` - Your expense/revenue file

## 📁 Project Structure

```
your-project/
├── transaction_editor.py
├── main.py
├── llcAssets_WBGroupLLC.json
└── llcExpRev_WBGroupLLC.json
```

## 🚀 Starting the Editor

### Basic Usage

```bash
# Both editors (recommended)
python main.py --assets llcAssets_WBGroupLLC.json --exprev llcExpRev_WBGroupLLC.json

# Just assets
python main.py --assets llcAssets_WBGroupLLC.json

# Just expense/revenue
python main.py --exprev llcExpRev_WBGroupLLC.json
```

### Advanced Options

```bash
# Custom port
python main.py --assets llcAssets_WBGroupLLC.json --port 8080

# Debug mode (auto-reload on code changes)
python main.py --assets llcAssets_WBGroupLLC.json --debug

# Allow network access (accessible from other computers)
python main.py --assets llcAssets_WBGroupLLC.json --host 0.0.0.0

# Don't open browser automatically
python main.py --assets llcAssets_WBGroupLLC.json --no-browser

# Combine options
python main.py \
  --assets llcAssets_WBGroupLLC.json \
  --exprev llcExpRev_WBGroupLLC.json \
  --port 8080 \
  --debug
```

## 🛑 Stopping the Editor

### Method 1: Keyboard Interrupt (Recommended)

Press **Ctrl+C** in the terminal where the server is running.

```
✅ Server is running!
⚠️  Press Ctrl+C to stop the server

^C
🛑 Shutting down server...
✅ Server stopped successfully!
```

### Method 2: Use the Logoff Button

1. In the web interface, click "🚪 Save & Logoff"
2. Confirms saving all changes
3. Shuts down the server
4. Terminal will show shutdown message

### Method 3: Close Terminal (Not Recommended)

Simply close the terminal window. This works but doesn't allow graceful shutdown.

## 📖 Command Line Options Reference

| Option | Description | Default | Example |
|--------|-------------|---------|---------|
| `--load` | load temp files | `--load |
| `--edOpt` | llc, llcAssets, llcExpRev | llc | `--edOpt=llc |
| `--port PORT` | Server port number | 5000 | `--port 8080` |
| `--host HOST` | Server host address | 127.0.0.1 | `--host 0.0.0.0` |
| `--debug` | Enable debug mode | False | `--debug` |
| `--no-browser` | Don't open browser | False | `--no-browser` |

## 🎯 Common Usage Scenarios

### Scenario 1: Local Development

```bash
python main.py \
  --assets llcAssets_WBGroupLLC.json \
  --exprev llcExpRev_WBGroupLLC.json \
  --debug
```

- Auto-reloads when you modify code
- Opens browser automatically
- Runs on localhost:5000

### Scenario 2: Production Use

```bash
python main.py \
  --assets llcAssets_WBGroupLLC.json \
  --exprev llcExpRev_WBGroupLLC.json \
  --no-browser
```

- No debug mode (more stable)
- Doesn't auto-open browser
- Manual browser navigation to http://localhost:5000

### Scenario 3: Network Access

```bash
python main.py \
  --assets llcAssets_WBGroupLLC.json \
  --exprev llcExpRev_WBGroupLLC.json \
  --host 0.0.0.0 \
  --port 8080
```

- Accessible from other devices on your network
- Access via: http://YOUR_IP:8080
- Find your IP: `ipconfig` (Windows) or `ifconfig` (Mac/Linux)

### Scenario 4: Quick Asset-Only Edit

```bash
python main.py --assets llcAssets_WBGroupLLC.json
```

- Fastest startup
- Only asset editor available
- Default settings

## 🔍 Accessing the Editor

After starting, the editor is accessible at:

- **Default:** http://localhost:5000
- **Custom port:** http://localhost:YOUR_PORT
- **Network:** http://YOUR_IP:YOUR_PORT

## 💾 File Management

### Auto-Creation of Files

If your JSON files don't exist, they'll be created when you:
1. Add your first transaction
2. Click "Save to File"

### Backup Recommendation

```bash
# Before starting, backup your files
cp llcAssets_WBGroupLLC.json llcAssets_BACKUP_$(date +%Y%m%d).json
cp llcExpRev_WBGroupLLC.json llcExpRev_BACKUP_$(date +%Y%m%d).json

# Then start editor
python main.py --assets llcAssets_WBGroupLLC.json --exprev llcExpRev_WBGroupLLC.json
```

## 🔧 Troubleshooting

### Port Already in Use

```
Error: Address already in use
```

**Solution:** Use a different port
```bash
python main.py --assets llcAssets.json --port 5001
```

### File Not Found

```
⚠️ Warning: Asset file 'llcAssets.json' not found
```

**This is OK** - The file will be created when you save your first transaction.

### Cannot Connect to Server

1. Check if server is running in terminal
2. Verify the port number
3. Try http://127.0.0.1:5000 instead of localhost
4. Check firewall settings

### Module Not Found

```
ModuleNotFoundError: No module named 'flask'
```

**Solution:** Install Flask
```bash
pip install flask
```

### Changes Not Saving

- Make sure to click "💾 Save to File" button
- Check terminal for error messages
- Verify file permissions (write access)

## 🎓 Step-by-Step First Run

### 1. Install Dependencies

```bash
pip install flask
```

### 2. Navigate to Project Directory

```bash
cd /path/to/your/project
```

### 3. Verify Files Exist

```bash
ls -la
# Should see: transaction_editor.py, main.py, and your JSON files
```

### 4. Start the Server

```bash
python main.py --assets llcAssets_WBGroupLLC.json --exprev llcExpRev_WBGroupLLC.json
```

### 5. Wait for Browser to Open

```
🚀 Starting Transaction Editor...
📍 Server: http://127.0.0.1:5000
📁 Assets: llcAssets_WBGroupLLC.json
✅ Loaded 13 assets from llcAssets_WBGroupLLC.json
📁 Expense/Revenue: llcExpRev_WBGroupLLC.json
✅ Loaded 0 exprev from llcExpRev_WBGroupLLC.json

🌐 Opening browser at http://127.0.0.1:5000...

✅ Server is running!
⚠️  Press Ctrl+C to stop the server
```

### 6. Use the Editor

- Front page shows both editors
- Click "Asset Editor" or "Expense/Revenue Editor"
- Make your changes
- Click "💾 Save to File" to persist changes

### 7. Stop the Server

Press **Ctrl+C** in the terminal

```
^C
🛑 Shutting down server...
✅ Server stopped successfully!
```

## 🔐 Security Notes

### Local Access Only (Default)

```bash
python main.py --assets llcAssets.json
```
- Only accessible from your computer
- Safe for sensitive financial data

### Network Access (Use with Caution)

```bash
python main.py --assets llcAssets.json --host 0.0.0.0
```
- **Warning:** Accessible to anyone on your network
- No authentication/encryption
- Only use on trusted private networks
- Consider using a VPN for remote access

## 📊 Monitoring

While the server runs, the terminal shows:

```
🚀 Starting Transaction Editor...
📍 Server: http://127.0.0.1:5000
📁 Assets: llcAssets_WBGroupLLC.json
✅ Loaded 13 assets from llcAssets_WBGroupLLC.json
📁 Expense/Revenue: llcExpRev_WBGroupLLC.json
✅ Loaded 0 exprev from llcExpRev_WBGroupLLC.json

127.0.0.1 - - [07/Apr/2026 10:30:15] "GET / HTTP/1.1" 200 -
127.0.0.1 - - [07/Apr/2026 10:30:20] "GET /assets HTTP/1.1" 200 -
127.0.0.1 - - [07/Apr/2026 10:30:25] "GET /api/assets/list HTTP/1.1" 200 -
```

Each line shows:
- IP address accessing the server
- Timestamp
- HTTP method and path
- Status code

## 💡 Pro Tips

### 1. Create an Alias (Mac/Linux)

Add to your `~/.bashrc` or `~/.zshrc`:

```bash
alias edit-llc='cd ~/llc-accounting && python main.py --assets llcAssets_WBGroupLLC.json --exprev llcExpRev_WBGroupLLC.json'
```

Then just run: `edit-llc`

### 2. Create a Batch File (Windows)

Create `start-editor.bat`:

```batch
@echo off
cd C:\path\to\your\project
python main.py --assets llcAssets_WBGroupLLC.json --exprev llcExpRev_WBGroupLLC.json
pause
```

Double-click to start!

### 3. Background Process (Linux/Mac)

```bash
# Start in background
nohup python main.py --assets llcAssets.json --no-browser > server.log 2>&1 &

# View log
tail -f server.log

# Stop
pkill -f main.py
```

### 4. Auto-Backup on Start

Create `start-with-backup.sh`:

```bash
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
cp llcAssets_WBGroupLLC.json backups/llcAssets_${DATE}.json
cp llcExpRev_WBGroupLLC.json backups/llcExpRev_${DATE}.json
python main.py --assets llcAssets_WBGroupLLC.json --exprev llcExpRev_WBGroupLLC.json
```

## 🆘 Getting Help

### View Help

```bash
python main.py --help
```

Shows all available options and examples.

### Check Version

```bash
python --version
```

Ensure Python 3.7 or higher.

### Test Flask Installation

```bash
python -c "import flask; print(flask.__version__)"
```

Should print Flask version (e.g., 3.0.0).

---

## 🎉 Run App

Start editing your LLC transactions with:

```bash
python main.py --assets llcAssets_WBGroupLLC.json --exprev llcExpRev_WBGroupLLC.json
```

Happy accounting! 💼📊