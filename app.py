"""
图片生成工作流 - Flask后端应用
通过扣子平台 API 调用图像生成工作流
"""

import os
import re
import uuid
import time
import base64
import shutil
import requests
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_file
from werkzeug.utils import secure_filename
import threading
import queue

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max upload
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# 存储目录
UPLOAD_FOLDER = '/tmp/uploads'
OUTPUT_FOLDER = '/tmp/outputs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# 扣子平台配置
COZE_API_URL = os.environ.get('COZE_API_URL', '')  # 例如: https://xxxx.coze.site/run
COZE_API_TOKEN = os.environ.get('COZE_API_TOKEN', '')  # 扣子工作流的 API Token
COZE_WORKFLOW_ID = os.environ.get('COZE_WORKFLOW_ID', '')  # 工作流ID（可选）

# 任务存储
tasks = {}
tasks_lock = threading.Lock()

# 尺寸映射
SIZE_MAPPING = {
    '1:1': {'width': 1024, 'height': 1024},
    '3:4': {'width': 896, 'height': 1152},
    '16:9': {'width': 1024, 'height': 576},
}


def save_uploaded_file(file, subfolder=''):
    """保存上传的文件"""
    if not file:
        return None
    
    filename = secure_filename(file.filename)
    ext = os.path.splitext(filename)[1] or '.png'
    unique_name = f"{uuid.uuid4().hex}{ext}"
    
    folder = os.path.join(UPLOAD_FOLDER, subfolder) if subfolder else UPLOAD_FOLDER
    os.makedirs(folder, exist_ok=True)
    
    filepath = os.path.join(folder, unique_name)
    file.save(filepath)
    return filepath


def image_to_base64(image_path):
    """将图片转换为 base64 编码"""
    with open(image_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')


def call_coze_workflow(prompt, width, height, ref_image_base64=None, product_image_base64=None):
    """
    调用扣子平台的图像生成工作流
    
    Args:
        prompt: 提示词
        width: 宽度
        height: 高度
        ref_image_base64: 参考图 base64（可选）
        product_image_base64: 产品图 base64（可选）
    
    Returns:
        dict: 包含图片URL列表或错误信息
    """
    if not COZE_API_URL or not COZE_API_TOKEN:
        # 如果没有配置，使用模拟数据返回
        return {
            'success': False,
            'error': '扣子API未配置，请设置 COZE_API_URL 和 COZE_API_TOKEN 环境变量'
        }
    
    try:
        # 构建请求数据
        payload = {
            'prompt': prompt,
            'width': width,
            'height': height,
        }
        
        # 如果有参考图或产品图，添加到请求中
        if ref_image_base64:
            payload['ref_image'] = ref_image_base64
        if product_image_base64:
            payload['product_image'] = product_image_base64
        
        # 调用扣子 API
        headers = {
            'Authorization': f'Bearer {COZE_API_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        response = requests.post(
            COZE_API_URL,
            json=payload,
            headers=headers,
            timeout=300
        )
        
        if response.status_code == 200:
            result = response.json()
            return {
                'success': True,
                'data': result
            }
        else:
            return {
                'success': False,
                'error': f'API调用失败: {response.status_code} - {response.text}'
            }
            
    except requests.exceptions.Timeout:
        return {
            'success': False,
            'error': 'API调用超时，请重试'
        }
    except Exception as e:
        return {
            'success': False,
            'error': f'API调用错误: {str(e)}'
        }


def download_and_save_image(url, output_path):
    """下载图片并保存到本地"""
    try:
        response = requests.get(url, timeout=60)
        if response.status_code == 200:
            with open(output_path, 'wb') as f:
                f.write(response.content)
            return True
        return False
    except Exception:
        return False


def process_generation_task(task_id):
    """异步处理图片生成任务"""
    try:
        with tasks_lock:
            task = tasks.get(task_id)
            if not task:
                return
            task['status'] = 'processing'
        
        # 获取参数
        prompt = task['prompt']
        size_option = task['size']
        custom_width = task.get('custom_width')
        custom_height = task.get('custom_height')
        count = task.get('count', 1)
        product_path = task.get('product_image')
        ref_path = task.get('ref_image')
        
        # 确定尺寸
        if size_option == 'custom':
            width = int(custom_width) if custom_width else 1024
            height = int(custom_height) if custom_height else 1024
        else:
            size_info = SIZE_MAPPING.get(size_option, SIZE_MAPPING['1:1'])
            width = size_info['width']
            height = size_info['height']
        
        # 转换图片为 base64
        product_base64 = image_to_base64(product_path) if product_path and os.path.exists(product_path) else None
        ref_base64 = image_to_base64(ref_path) if ref_path and os.path.exists(ref_path) else None
        
        generated_images = []
        
        # 根据数量生成图片
        for i in range(count):
            # 更新进度
            with tasks_lock:
                task['progress'] = int((i + 0.5) / count * 100)
                task['progress_text'] = f'正在生成第 {i+1}/{count} 张图片...'
            
            # 调用扣子 API
            result = call_coze_workflow(
                prompt=prompt,
                width=width,
                height=height,
                ref_image_base64=ref_base64,
                product_image_base64=product_base64
            )
            
            if not result.get('success'):
                continue
            
            data = result.get('data', {})
            
            # 提取图片URL（根据实际API返回格式调整）
            image_urls = []
            
            # 尝试从不同的返回格式中提取图片URL
            if isinstance(data, dict):
                # 格式1: {output: "url"}
                if 'output' in data:
                    output = data['output']
                    if isinstance(output, str):
                        image_urls.append(output)
                    elif isinstance(output, list):
                        image_urls.extend(output)
                    elif isinstance(output, dict) and 'image_urls' in output:
                        image_urls.extend(output.get('image_urls', []))
                
                # 格式2: {image_urls: [...]}  
                elif 'image_urls' in data:
                    image_urls.extend(data['image_urls'])
                    
                # 格式3: {data: {image_urls: [...]}}
                elif 'data' in data and isinstance(data['data'], dict):
                    image_urls.extend(data['data'].get('image_urls', []))
            
            # 下载每张图片
            for idx, url in enumerate(image_urls):
                output_name = f"{task_id}_{i}_{idx}_{uuid.uuid4().hex[:8]}.png"
                output_path = os.path.join(OUTPUT_FOLDER, output_name)
                
                if download_and_save_image(url, output_path):
                    generated_images.append(output_path)
        
        # 更新任务状态
        with tasks_lock:
            task = tasks.get(task_id)
            if task:
                if generated_images:
                    task['status'] = 'completed'
                    task['images'] = generated_images
                    task['progress'] = 100
                    task['progress_text'] = '生成完成'
                else:
                    task['status'] = 'failed'
                    task['error'] = '未能生成任何图片'
                    task['progress_text'] = '生成失败'
                
    except Exception as e:
        with tasks_lock:
            task = tasks.get(task_id)
            if task:
                task['status'] = 'failed'
                task['error'] = str(e)


@app.route('/')
def index():
    """首页"""
    return render_template('index.html')


@app.route('/api/generate', methods=['POST'])
def create_generation_task():
    """创建图片生成任务"""
    try:
        # 获取参数
        product_image = request.files.get('product_image')
        ref_image = request.files.get('ref_image')
        prompt = request.form.get('prompt', '').strip()
        size_option = request.form.get('size', '1:1')
        custom_width = request.form.get('custom_width', '')
        custom_height = request.form.get('custom_height', '')
        count = int(request.form.get('count', 1))
        
        # 验证必填项
        if not prompt:
            return jsonify({'error': '请输入生成提示词'}), 400
        
        # 限制数量
        count = max(1, min(4, count))
        
        # 保存上传的文件
        product_path = save_uploaded_file(product_image, 'products') if product_image else None
        ref_path = save_uploaded_file(ref_image, 'references') if ref_image else None
        
        # 创建任务
        task_id = str(uuid.uuid4())
        
        with tasks_lock:
            tasks[task_id] = {
                'status': 'pending',
                'created_at': datetime.now().isoformat(),
                'product_image': product_path,
                'ref_image': ref_path,
                'prompt': prompt,
                'size': size_option,
                'custom_width': custom_width,
                'custom_height': custom_height,
                'count': count,
                'images': [],
                'progress': 0,
                'progress_text': '等待处理...',
                'error': None
            }
        
        # 启动异步任务
        thread = threading.Thread(
            target=process_generation_task,
            args=(task_id,)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'task_id': task_id,
            'message': '任务已创建，图片生成中...'
        })
        
    except Exception as e:
        return jsonify({'error': f'创建任务失败: {str(e)}'}), 500


@app.route('/api/status/<task_id>')
def get_task_status(task_id):
    """查询任务状态"""
    with tasks_lock:
        task = tasks.get(task_id)
    
    if not task:
        return jsonify({'error': '任务不存在'}), 404
    
    return jsonify({
        'task_id': task_id,
        'status': task['status'],
        'progress': task.get('progress', 0),
        'progress_text': task.get('progress_text', ''),
        'images': [
            {
                'id': os.path.basename(img),
                'path': img,
                'url': f'/api/download/{os.path.basename(img)}'
            }
            for img in task.get('images', [])
        ],
        'error': task.get('error')
    })


@app.route('/api/download/<filename>')
def download_image(filename):
    """下载图片"""
    # 防止路径遍历
    filename = secure_filename(filename)
    filepath = os.path.join(OUTPUT_FOLDER, filename)
    
    if not os.path.exists(filepath):
        return jsonify({'error': '文件不存在'}), 404
    
    return send_file(
        filepath,
        mimetype='image/png',
        as_attachment=True,
        download_name=filename
    )


@app.route('/api/preview/<filename>')
def preview_file(filename):
    """预览上传的文件"""
    filename = secure_filename(filename)
    
    # 尝试多个目录
    for subfolder in ['temp', 'products', 'references', '']:
        if subfolder:
            filepath = os.path.join(UPLOAD_FOLDER, subfolder, filename)
        else:
            filepath = os.path.join(UPLOAD_FOLDER, filename)
        
        if os.path.exists(filepath):
            return send_file(filepath)
    
    return jsonify({'error': '文件不存在'}), 404


@app.route('/api/health')
def health_check():
    """健康检查"""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'coze_configured': bool(COZE_API_URL and COZE_API_TOKEN)
    })


@app.route('/api/config')
def get_config():
    """获取配置状态"""
    return jsonify({
        'coze_configured': bool(COZE_API_URL and COZE_API_TOKEN),
        'api_url': COZE_API_URL[:20] + '...' if COZE_API_URL else None
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
