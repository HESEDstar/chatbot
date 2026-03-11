from flask import Blueprint, send_from_directory, current_app, abort
# from app.api.middleware import require_auth_optional
import os
from hesedbot.config import Config


downloads_bp = Blueprint('downloads', __name__)
@downloads_bp.route('/files/<filename>', methods=['GET'])
# @require_auth_optional  <-- Uncomment to restrict downloads to logged-in users
def download_file(filename):
    """
    Endpoint to download generated lesson note PDFs.
    """
    # Security: Ensure filename is safe (basic check)
    if ".." in filename or filename.startswith("/"):
        abort(400)
        
    upload_folder = Config.UPLOAD_FOLDER # current_app.config['UPLOAD_FOLDER']
    
    try:
        return send_from_directory(
            upload_folder, 
            filename, 
            mimetype='application/pdf', 
            as_attachment=True, # Forces download prompt
            download_name=filename
        )
    except FileNotFoundError:
        abort(404)

