"""
Flask Asset Editor for Jupyter Notebook
Manages JSON asset data with full CRUD operations
"""

import json
import threading
from flask import Flask, render_template_string, request, jsonify
from IPython.display import IFrame, display
import copy

class uiEditorAssets:
    """
    A Flask-based asset editor that runs in Jupyter notebooks.
    
    Usage:
        editor = AssetEditor('llcAssets_WBGroupLLC.json')
        editor.start(port=5000)
        # To stop: editor.stop()
    """
    
    def __init__(self, json_file):
        """Initialize the asset editor with a JSON file."""
        self.json_file = json_file
        self.assets = []
        self.original_assets = []
        self.load_assets()
        
        # Flask app setup
        self.app = Flask(__name__)
        self.app.secret_key = 'asset-editor-secret-key'
        self.setup_routes()
        self.server = None
        
    def load_assets(self):
        """Load assets from JSON file."""
        try:
            with open(self.json_file, 'r') as f:
                self.assets = json.load(f)
                self.original_assets = copy.deepcopy(self.assets)
            print(f"✅ Loaded {len(self.assets)} assets from {self.json_file}")
        except FileNotFoundError:
            print(f"⚠️ File {self.json_file} not found. Starting with empty asset list.")
            self.assets = []
        except json.JSONDecodeError as e:
            print(f"❌ Error parsing JSON: {e}")
            self.assets = []
    
    def save_assets(self):
        """Save assets to JSON file."""
        try:
            with open(self.json_file, 'w') as f:
                json.dump(self.assets, f, indent=2)
            return True
        except Exception as e:
            print(f"❌ Error saving: {e}")
            return False
    
    def setup_routes(self):
        """Setup Flask routes."""
        
        @self.app.route('/')
        def index():
            """Main page with asset table."""
            return render_template_string(self.HTML_TEMPLATE)
        
        @self.app.route('/api/assets', methods=['GET'])
        def get_assets():
            """Get all assets."""
            return jsonify(self.assets)
        
        @self.app.route('/api/assets/<int:index>', methods=['GET'])
        def get_asset(index):
            """Get single asset by index."""
            if 0 <= index < len(self.assets):
                return jsonify({'success': True, 'asset': self.assets[index], 'index': index})
            return jsonify({'success': False, 'message': 'Asset not found'}), 404
        
        @self.app.route('/api/assets/<int:index>', methods=['PUT'])
        def update_asset(index):
            """Update asset at index."""
            if 0 <= index < len(self.assets):
                data = request.json
                self.assets[index] = data
                return jsonify({'success': True, 'asset': data})
            return jsonify({'success': False, 'message': 'Asset not found'}), 404
        
        @self.app.route('/api/assets/<int:index>', methods=['DELETE'])
        def delete_asset(index):
            """Delete asset at index."""
            if 0 <= index < len(self.assets):
                deleted = self.assets.pop(index)
                return jsonify({'success': True, 'deleted': deleted})
            return jsonify({'success': False, 'message': 'Asset not found'}), 404
        
        @self.app.route('/api/assets', methods=['POST'])
        def add_asset():
            """Add new asset."""
            data = request.json
            self.assets.append(data)
            return jsonify({'success': True, 'asset': data, 'index': len(self.assets) - 1})
        
        @self.app.route('/api/save', methods=['POST'])
        def save():
            """Save assets to file."""
            if self.save_assets():
                return jsonify({'success': True, 'message': f'Saved {len(self.assets)} assets'})
            return jsonify({'success': False, 'message': 'Error saving file'}), 500
        
        @self.app.route('/api/stats', methods=['GET'])
        def get_stats():
            """Get statistics about assets."""
            total_amt = sum(asset.get('amt', 0) for asset in self.assets)
            asset_types = {}
            for asset in self.assets:
                atype = asset.get('aType', 'Unknown')
                asset_types[atype] = asset_types.get(atype, 0) + 1
            
            return jsonify({
                'total_assets': len(self.assets),
                'total_amount': total_amt,
                'asset_types': asset_types,
                'unsaved_changes': self.assets != self.original_assets
            })
        
        @self.app.route('/api/shutdown', methods=['POST'])
        def shutdown():
            """Shutdown the Flask server."""
            func = request.environ.get('werkzeug.server.shutdown')
            if func is None:
                return jsonify({'success': False, 'message': 'Not running with the Werkzeug Server'})
            func()
            return jsonify({'success': True, 'message': 'Server shutting down...'})
    
    def start(self, port=5000, height=800, **kwargs):
        """Start the Flask server and display in Jupyter."""
        def run_server():
            self.app.run(port=port, debug=kwargs.get('debug', False), use_reloader=False)
        
        # Start server in background thread
        self.server = threading.Thread(target=run_server, daemon=True)
        self.server.start()
        
        # Display in Jupyter
        print(f"🚀 Asset Editor running at http://localhost:{port}")
        print(f"📁 Editing: {self.json_file}")
        print(f"📊 {len(self.assets)} assets loaded")
        print("\n⚠️ Remember to click 'Save to File' to persist changes!")
        
        # Show the interface
        display(IFrame(f'http://localhost:{port}', width='100%', height=height))
    
    def stop(self):
        """Stop the server (note: Flask doesn't stop easily in threads)."""
        print("⚠️ To fully stop the server, restart the Jupyter kernel.")
    
    # HTML Template with full UI
    HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Asset Editor</title>
    <meta charset="UTF-8">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
        }
        
        .container { max-width: 1400px; margin: 0 auto; }
        
        .header {
            background: white;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .header h1 {
            color: #667eea;
            margin: 0;
        }
        
        .stats {
            display: flex;
            gap: 20px;
            margin-bottom: 20px;
        }
        
        .stat-card {
            background: white;
            padding: 15px 20px;
            border-radius: 10px;
            flex: 1;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        .stat-value {
            font-size: 24px;
            font-weight: bold;
            color: #667eea;
        }
        
        .stat-label {
            font-size: 12px;
            color: #666;
            margin-top: 5px;
        }
        
        .card {
            background: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 4px 10px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        
        .toolbar {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }
        
        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 5px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
        }
        
        .btn-primary { background: #667eea; color: white; }
        .btn-success { background: #28a745; color: white; }
        .btn-warning { background: #ffc107; color: #333; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-info { background: #17a2b8; color: white; }
        .btn-sm { padding: 6px 12px; font-size: 12px; }
        
        .btn:hover { opacity: 0.9; transform: translateY(-2px); }
        
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }
        
        thead {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            position: sticky;
            top: 0;
        }
        
        th, td {
            padding: 12px 8px;
            text-align: left;
            border-bottom: 1px solid #e1e8ed;
        }
        
        th { font-weight: 600; }
        
        tbody tr:hover { background: #f8f9fa; }
        
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.5);
            overflow-y: auto;
        }
        
        .modal.active {
            display: flex;
            align-items: flex-start;
            justify-content: center;
            padding: 20px;
        }
        
        .modal-content {
            background: white;
            padding: 30px;
            border-radius: 10px;
            max-width: 800px;
            width: 100%;
            margin: 20px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.3);
            max-height: 90vh;
            overflow-y: auto;
        }
        
        .modal-header {
            border-bottom: 2px solid #eee;
            padding-bottom: 15px;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .modal-header h2 {
            margin: 0;
            color: #667eea;
        }
        
        .close-btn {
            font-size: 28px;
            color: #aaa;
            cursor: pointer;
            background: none;
            border: none;
            padding: 0;
        }
        
        .close-btn:hover { color: #333; }
        
        .form-group {
            margin-bottom: 15px;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 5px;
            font-weight: 600;
            color: #333;
            font-size: 13px;
        }
        
        .form-control {
            width: 100%;
            padding: 10px;
            border: 2px solid #e1e8ed;
            border-radius: 5px;
            font-size: 14px;
        }
        
        .form-control:focus {
            outline: none;
            border-color: #667eea;
        }
        
        textarea.form-control {
            min-height: 100px;
            font-family: monospace;
            resize: vertical;
        }
        
        .modal-footer {
            border-top: 2px solid #eee;
            padding-top: 15px;
            margin-top: 20px;
            display: flex;
            gap: 10px;
            justify-content: flex-end;
        }
        
        .alert {
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
            font-weight: 500;
        }
        
        .alert-success { background: #d4edda; color: #155724; }
        .alert-danger { background: #f8d7da; color: #721c24; }
        .alert-info { background: #d1ecf1; color: #0c5460; }
        
        .json-preview {
            background: #f4f4f4;
            padding: 15px;
            border-radius: 5px;
            font-family: monospace;
            font-size: 12px;
            white-space: pre-wrap;
            word-break: break-all;
            max-height: 300px;
            overflow-y: auto;
        }
        
        .field-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 15px;
        }
        
        .field-grid.full {
            grid-template-columns: 1fr;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>💼 Asset Editor</h1>
            <div>
                <button class="btn btn-success" onclick="saveToFile()">💾 Save to File</button>
                <button class="btn btn-info" onclick="loadStats()">🔄 Refresh</button>
                <button class="btn btn-danger" onclick="logoff()">🚪 Save & Logoff</button>
            </div>
        </div>
        
        <div id="alert-container"></div>
        
        <div class="stats">
            <div class="stat-card">
                <div class="stat-value" id="stat-total">0</div>
                <div class="stat-label">Total Assets</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="stat-amount">$0.00</div>
                <div class="stat-label">Total Amount</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="stat-types">0</div>
                <div class="stat-label">Asset Types</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="stat-changes">No</div>
                <div class="stat-label">Unsaved Changes</div>
            </div>
        </div>
        
        <div class="card">
            <div class="toolbar">
                <button class="btn btn-primary" onclick="openAddDialog()">➕ Add Asset</button>
                <select id="acct-filter" class="form-control" style="max-width: 300px;" onchange="filterAssets()">
                    <option value="">All Accounts</option>
                </select>
                <input type="text" id="search-box" class="form-control" 
                       placeholder="🔍 Search by propNm, desc, ledger..." 
                       style="max-width: 300px;" onkeyup="filterAssets()">
            </div>
            
            <div style="overflow-x: auto;">
                <table id="assets-table">
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Property</th>
                            <th>Date</th>
                            <th>Amount</th>
                            <th>Type</th>
                            <th>Account</th>
                            <th>Ledger</th>
                            <th>Description</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody id="assets-tbody">
                        <tr><td colspan="9" style="text-align: center; padding: 40px;">Loading...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- Edit Asset Modal -->
    <div id="editModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h2 id="modal-title">Edit Asset</h2>
                <button class="close-btn" onclick="closeEditDialog()">&times;</button>
            </div>
            
            <div id="edit-form-container">
                <!-- Form will be generated dynamically -->
            </div>
            
            <div class="modal-footer">
                <button class="btn btn-primary" onclick="saveAsset()">💾 Save</button>
                <button class="btn btn-warning" onclick="showJsonEditor()">📝 Edit JSON</button>
                <button class="btn btn-danger" onclick="closeEditDialog()">✖ Cancel</button>
            </div>
        </div>
    </div>

    <!-- JSON Editor Modal -->
    <div id="jsonModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h2>JSON Editor</h2>
                <button class="close-btn" onclick="closeJsonDialog()">&times;</button>
            </div>
            
            <div class="form-group">
                <label>Edit Raw JSON:</label>
                <textarea id="json-editor" class="form-control" style="min-height: 400px;"></textarea>
            </div>
            
            <div class="modal-footer">
                <button class="btn btn-success" onclick="saveJsonEdit()">💾 Save JSON</button>
                <button class="btn btn-danger" onclick="closeJsonDialog()">✖ Cancel</button>
            </div>
        </div>
    </div>

    <!-- Delete Confirmation Modal -->
    <div id="deleteModal" class="modal">
        <div class="modal-content" style="max-width: 500px;">
            <div class="modal-header">
                <h2>⚠️ Confirm Delete</h2>
                <button class="close-btn" onclick="closeDeleteDialog()">&times;</button>
            </div>
            
            <p style="margin: 20px 0;">Are you sure you want to delete this asset?</p>
            <div id="delete-preview" class="json-preview"></div>
            
            <div class="modal-footer">
                <button class="btn btn-danger" onclick="confirmDelete()">Yes, Delete</button>
                <button class="btn btn-primary" onclick="closeDeleteDialog()">Cancel</button>
            </div>
        </div>
    </div>

    <script>
        let assets = [];
        let currentEditIndex = null;
        let currentDeleteIndex = null;
        let allAssets = [];
        let uniqueAccounts = new Set();

        // Load assets on page load
        document.addEventListener('DOMContentLoaded', function() {
            loadAssets();
            loadStats();
        });

        function loadAssets() {
            fetch('/api/assets')
                .then(r => r.json())
                .then(data => {
                    assets = data;
                    allAssets = data;
                    
                    // Build unique accounts for filter
                    uniqueAccounts = new Set();
                    data.forEach(asset => {
                        if (asset.acct) {
                            uniqueAccounts.add(asset.acct);
                        }
                    });
                    
                    populateAccountFilter();
                    renderAssets(assets);
                })
                .catch(err => showAlert('Error loading assets', 'danger'));
        }

        function populateAccountFilter() {
            const select = document.getElementById('acct-filter');
            const sortedAccounts = Array.from(uniqueAccounts).sort();
            
            let options = '<option value="">All Accounts</option>';
            sortedAccounts.forEach(acct => {
                options += `<option value="${acct}">${acct}</option>`;
            });
            
            select.innerHTML = options;
        }

        function loadStats() {
            fetch('/api/stats')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('stat-total').textContent = data.total_assets;
                    document.getElementById('stat-amount').textContent = 
                        '$' + data.total_amount.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
                    document.getElementById('stat-types').textContent = 
                        Object.keys(data.asset_types).length;
                    document.getElementById('stat-changes').textContent = 
                        data.unsaved_changes ? 'Yes ⚠️' : 'No ✅';
                    document.getElementById('stat-changes').style.color = 
                        data.unsaved_changes ? '#dc3545' : '#28a745';
                });
        }

        function renderAssets(assetsToRender) {
            const tbody = document.getElementById('assets-tbody');
            
            if (assetsToRender.length === 0) {
                tbody.innerHTML = '<tr><td colspan="9" style="text-align: center; padding: 40px;">No assets found</td></tr>';
                return;
            }
            
            tbody.innerHTML = assetsToRender.map((asset, index) => {
                // Find the original index in allAssets array
                const originalIndex = allAssets.findIndex(a => JSON.stringify(a) === JSON.stringify(asset));
                
                return `
                <tr>
                    <td><strong>${originalIndex + 1}</strong></td>
                    <td>${asset.propNm || ''}</td>
                    <td>${asset.dt || ''}</td>
                    <td><strong>${(asset.amt || 0).toFixed(2)}</strong></td>
                    <td><span style="background: #e1e8ed; padding: 3px 8px; border-radius: 3px;">${asset.aType || ''}</span></td>
                    <td style="font-size: 11px;">${asset.acct || ''}</td>
                    <td style="font-size: 11px;">${asset.Ledger || ''}</td>
                    <td style="max-width: 200px; overflow: hidden; text-overflow: ellipsis;">${asset.desc || ''}</td>
                    <td>
                        <button class="btn btn-warning btn-sm" onclick="openEditDialog(${originalIndex})">✏️</button>
                        <button class="btn btn-danger btn-sm" onclick="openDeleteDialog(${originalIndex})">🗑️</button>
                    </td>
                </tr>
            `}).join('');
        }

        function filterAssets() {
            const search = document.getElementById('search-box').value.toLowerCase();
            const acctFilter = document.getElementById('acct-filter').value;
            
            let filtered = allAssets;
            
            // Filter by account if selected
            if (acctFilter) {
                filtered = filtered.filter(asset => asset.acct === acctFilter);
            }
            
            // Filter by search text
            if (search) {
                filtered = filtered.filter(asset => {
                    return JSON.stringify(asset).toLowerCase().includes(search);
                });
            }
            
            renderAssets(filtered);
        }

        function openAddDialog() {
            currentEditIndex = null;
            const newAsset = {
                aID: '',
                addr: '',
                amt: 0.0,
                dt: '',
                stakeholderPct: {},
                acct: '',
                aType: '',
                propNm: '',
                propRef: '',
                desc: '',
                Ledger: '',
                kwList: []
            };
            
            showEditForm(newAsset);
            document.getElementById('modal-title').textContent = 'Add New Asset';
            document.getElementById('editModal').classList.add('active');
        }

        function openEditDialog(index) {
            currentEditIndex = index;
            
            fetch(`/api/assets/${index}`)
                .then(r => r.json())
                .then(data => {
                    showEditForm(data.asset);
                    document.getElementById('modal-title').textContent = `Edit Asset #${index + 1}`;
                    document.getElementById('editModal').classList.add('active');
                })
                .catch(err => showAlert('Error loading asset', 'danger'));
        }

        function showEditForm(asset) {
            const container = document.getElementById('edit-form-container');
            
            const mainFields = ['aID', 'propNm', 'dt', 'amt', 'aType', 'acct', 'desc', 'addr', 'propRef', 'Ledger'];
            
            let html = '<div class="field-grid">';
            
            mainFields.forEach(field => {
                const value = asset[field] !== undefined ? asset[field] : '';
                const type = field === 'amt' ? 'number' : 'text';
                const step = field === 'amt' ? '0.01' : '';
                
                html += `
                    <div class="form-group">
                        <label>${field}:</label>
                        <input type="${type}" ${step ? 'step="' + step + '"' : ''} 
                               id="field-${field}" class="form-control" value="${value}">
                    </div>
                `;
            });
            
            html += '</div>';
            
            // Add JSON fields for complex objects
            html += '<div class="field-grid full">';
            html += `
                <div class="form-group">
                    <label>stakeholderPct (JSON):</label>
                    <textarea id="field-stakeholderPct" class="form-control" style="min-height: 60px;">${JSON.stringify(asset.stakeholderPct || {}, null, 2)}</textarea>
                </div>
                <div class="form-group">
                    <label>kwList (JSON):</label>
                    <textarea id="field-kwList" class="form-control" style="min-height: 60px;">${JSON.stringify(asset.kwList || [], null, 2)}</textarea>
                </div>
            `;
            html += '</div>';
            
            container.innerHTML = html;
        }

        function saveAsset() {
            const mainFields = ['aID', 'propNm', 'dt', 'amt', 'aType', 'acct', 'desc', 'addr', 'propRef', 'Ledger'];
            
            const asset = {};
            
            mainFields.forEach(field => {
                const elem = document.getElementById(`field-${field}`);
                if (elem) {
                    asset[field] = field === 'amt' ? parseFloat(elem.value) : elem.value;
                }
            });
            
            try {
                asset.stakeholderPct = JSON.parse(document.getElementById('field-stakeholderPct').value);
                asset.kwList = JSON.parse(document.getElementById('field-kwList').value);
            } catch (e) {
                showAlert('Invalid JSON in stakeholderPct or kwList', 'danger');
                return;
            }
            
            const url = currentEditIndex !== null ? `/api/assets/${currentEditIndex}` : '/api/assets';
            const method = currentEditIndex !== null ? 'PUT' : 'POST';
            
            fetch(url, {
                method: method,
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(asset)
            })
            .then(r => r.json())
            .then(data => {
                closeEditDialog();
                loadAssets();
                loadStats();
                showAlert(currentEditIndex !== null ? 'Asset updated!' : 'Asset added!', 'success');
            })
            .catch(err => showAlert('Error saving asset', 'danger'));
        }

        function showJsonEditor() {
            const mainFields = ['aID', 'propNm', 'dt', 'amt', 'aType', 'acct', 'desc', 'addr', 'propRef', 'Ledger'];
            const asset = {};
            
            mainFields.forEach(field => {
                const elem = document.getElementById(`field-${field}`);
                if (elem) {
                    asset[field] = field === 'amt' ? parseFloat(elem.value) : elem.value;
                }
            });
            
            try {
                asset.stakeholderPct = JSON.parse(document.getElementById('field-stakeholderPct').value);
                asset.kwList = JSON.parse(document.getElementById('field-kwList').value);
            } catch (e) {}
            
            document.getElementById('json-editor').value = JSON.stringify(asset, null, 2);
            document.getElementById('jsonModal').classList.add('active');
        }

        function saveJsonEdit() {
            try {
                const asset = JSON.parse(document.getElementById('json-editor').value);
                
                const url = currentEditIndex !== null ? `/api/assets/${currentEditIndex}` : '/api/assets';
                const method = currentEditIndex !== null ? 'PUT' : 'POST';
                
                fetch(url, {
                    method: method,
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(asset)
                })
                .then(r => r.json())
                .then(data => {
                    closeJsonDialog();
                    closeEditDialog();
                    loadAssets();
                    loadStats();
                    showAlert('Asset saved from JSON!', 'success');
                });
            } catch (e) {
                showAlert('Invalid JSON: ' + e.message, 'danger');
            }
        }

        function openDeleteDialog(index) {
            currentDeleteIndex = index;
            
            fetch(`/api/assets/${index}`)
                .then(r => r.json())
                .then(data => {
                    document.getElementById('delete-preview').textContent = 
                        JSON.stringify(data.asset, null, 2);
                    document.getElementById('deleteModal').classList.add('active');
                });
        }

        function confirmDelete() {
            fetch(`/api/assets/${currentDeleteIndex}`, { method: 'DELETE' })
                .then(r => r.json())
                .then(data => {
                    closeDeleteDialog();
                    loadAssets();
                    loadStats();
                    showAlert('Asset deleted!', 'success');
                })
                .catch(err => showAlert('Error deleting asset', 'danger'));
        }

        function saveToFile() {
            fetch('/api/save', { method: 'POST' })
                .then(r => r.json())
                .then(data => {
                    showAlert(data.message + ' 💾', 'success');
                    loadStats();
                })
                .catch(err => showAlert('Error saving file', 'danger'));
        }

        function logoff() {
            if (confirm('Save changes and close the editor?')) {
                fetch('/api/save', { method: 'POST' })
                    .then(r => r.json())
                    .then(data => {
                        showAlert('Saved! Closing in 2 seconds...', 'success');
                        setTimeout(() => {
                            fetch('/api/shutdown', { method: 'POST' })
                                .then(() => {
                                    window.close();
                                    document.body.innerHTML = '<div style="text-align: center; padding: 50px; font-size: 20px;">✅ Editor closed. You can close this tab.</div>';
                                });
                        }, 2000);
                    })
                    .catch(err => showAlert('Error saving file', 'danger'));
            }
        }

        function closeEditDialog() {
            document.getElementById('editModal').classList.remove('active');
        }

        function closeJsonDialog() {
            document.getElementById('jsonModal').classList.remove('active');
        }

        function closeDeleteDialog() {
            document.getElementById('deleteModal').classList.remove('active');
        }

        function showAlert(message, type) {
            const container = document.getElementById('alert-container');
            container.innerHTML = `<div class="alert alert-${type}">${message}</div>`;
            setTimeout(() => container.innerHTML = '', 3000);
        }

        window.onclick = function(event) {
            if (event.target.classList.contains('modal')) {
                event.target.classList.remove('active');
            }
        }
    </script>
</body>
</html>
    '''


# Usage example for Jupyter Notebook:
"""
# In a Jupyter notebook cell:

from asset_editor import AssetEditor

# Create editor instance
editor = AssetEditor('llcAssets_WBGroupLLC.json')

# Start the editor (will display inline)
editor.start(port=5000, height=800)

# The editor will be displayed in the notebook
# Make your edits in the browser interface
# Click "Save to File" to persist changes

# To stop (requires kernel restart):
# editor.stop()
"""