from flask import Flask, request, jsonify
from api.downloads import downloads_bp
import os
from hesedbot.config import Config

def create_app():
    app = Flask(__name__)
    app.config['UPLOAD_FOLDER'] = Config.UPLOAD_FOLDER

    @app.route('/api/health', methods=['GET'])
    def health_check():
        return jsonify({"status": "ok"}), 200

    return app

app = create_app()
# Register blueprints
app.register_blueprint(downloads_bp, url_prefix='/api/downloads')
