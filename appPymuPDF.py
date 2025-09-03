from flask import Flask, render_template, request, jsonify, send_file
import pymupdf4llm
import os
import tempfile
import uuid
from datetime import datetime
import re

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = 'uploads'

# 업로드 폴더 생성
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def parse_page_numbers(page_input):
    """페이지 번호 문자열을 파싱하여 리스트로 변환"""
    try:
        page_numbers = []
        
        # 쉼표로 구분된 부분들을 처리
        parts = page_input.replace(' ', '').split(',')
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
                
            # 하이픈으로 구분된 범위 처리 (예: 1-3)
            if '-' in part:
                range_parts = part.split('-')
                if len(range_parts) == 2:
                    start = int(range_parts[0])
                    end = int(range_parts[1])
                    if start <= end:
                        page_numbers.extend(range(start, end + 1))
                    else:
                        page_numbers.extend(range(start, end - 1, -1))
                else:
                    return []
            else:
                # 단일 페이지 번호
                page_numbers.append(int(part))
        
        # 중복 제거 및 정렬
        page_numbers = sorted(list(set(page_numbers)))
        return page_numbers
        
    except (ValueError, IndexError):
        return []

def extract_tables_from_markdown(md_text):
    """마크다운 텍스트에서 테이블을 추출하여 딕셔너리로 변환"""
    tables = []
    
    try:
        # 1. 마크다운 테이블 형식 찾기 (|로 구분된 테이블)
        markdown_tables = extract_markdown_tables(md_text)
        tables.extend(markdown_tables)
        
        # 2. 마크다운에서 찾지 못한 경우, 텍스트 기반 테이블 감지
        if not tables:
            print("마크다운 테이블을 찾지 못함. 텍스트 기반 감지 시도...")
            text_tables = extract_tables_from_text(md_text)
            tables.extend(text_tables)
        
        print(f"총 추출된 테이블 수: {len(tables)}")
        
    except Exception as e:
        print(f"마크다운 테이블 추출 중 오류: {str(e)}")
    
    return tables

def extract_markdown_tables(md_text):
    """마크다운 형식의 테이블 추출"""
    tables = []
    
    # 마크다운 테이블 패턴 찾기
    table_pattern = r'\|.*\|.*\n\|[\s\-:|]+\|\n(\|.*\|\n)*'
    table_matches = re.finditer(table_pattern, md_text, re.MULTILINE)
    
    for i, match in enumerate(table_matches):
        table_text = match.group(0)
        lines = table_text.strip().split('\n')
        
        # 헤더와 데이터 분리
        if len(lines) >= 3:
            header_line = lines[0]
            separator_line = lines[1]
            data_lines = lines[2:]
            
            # 헤더 추출
            headers = [h.strip() for h in header_line.split('|')[1:-1]]
            
            # 데이터 추출
            data = []
            for line in data_lines:
                if line.strip():
                    row_data = [cell.strip() for cell in line.split('|')[1:-1]]
                    if len(row_data) == len(headers):
                        # 헤더와 데이터를 매핑하여 딕셔너리 생성
                        row_dict = {}
                        for j, header in enumerate(headers):
                            row_dict[header] = row_data[j] if j < len(row_data) else ''
                        data.append(row_dict)
            
            if headers and data:
                tables.append({
                    'id': f'md_table_{i}',
                    'title': f'마크다운 테이블 {i+1}',
                    'data': data,
                    'columns': headers
                })
    
    return tables

def extract_tables_from_text(text):
    """텍스트에서 테이블 패턴을 찾아 추출"""
    tables = []
    
    try:
        lines = text.split('\n')
        current_table = []
        in_table = False
        
        for line in lines:
            line = line.strip()
            if not line:
                if in_table and len(current_table) >= 2:
                    # 빈 줄로 테이블 종료
                    table = create_table_from_rows(current_table)
                    if table:
                        tables.append(table)
                current_table = []
                in_table = False
                continue
            
            # 다양한 구분자로 테이블 행 감지
            # 1. 탭으로 구분된 경우
            if '\t' in line:
                parts = line.split('\t')
            # 2. 여러 공백으로 구분된 경우
            elif re.search(r'\s{3,}', line):
                parts = re.split(r'\s{3,}', line)
            # 3. 콜론으로 구분된 경우 (키:값 형태)
            elif ':' in line and line.count(':') >= 1:
                parts = re.split(r'\s*:\s*', line)
            # 4. 파이프(|)로 구분된 경우
            elif '|' in line:
                parts = [p.strip() for p in line.split('|') if p.strip()]
            else:
                # 테이블이 아닌 경우
                if in_table and len(current_table) >= 2:
                    table = create_table_from_rows(current_table)
                    if table:
                        tables.append(table)
                current_table = []
                in_table = False
                continue
            
            # 의미있는 데이터가 있는지 확인
            meaningful_parts = [part.strip() for part in parts if part.strip() and len(part.strip()) > 0]
            if len(meaningful_parts) >= 2:
                current_table.append(meaningful_parts)
                in_table = True
            else:
                if in_table and len(current_table) >= 2:
                    table = create_table_from_rows(current_table)
                    if table:
                        tables.append(table)
                current_table = []
                in_table = False
        
        # 마지막 테이블 처리
        if in_table and len(current_table) >= 2:
            table = create_table_from_rows(current_table)
            if table:
                tables.append(table)
                
    except Exception as e:
        print(f"텍스트 테이블 추출 중 오류: {str(e)}")
    
    return tables

def create_table_from_rows(rows):
    """행 데이터로부터 테이블 딕셔너리 생성"""
    try:
        if len(rows) < 2:
            return None
        
        # 컬럼 수를 맞추기 위해 가장 긴 행의 길이를 기준으로 함
        max_cols = max(len(row) for row in rows)
        
        # 모든 행을 동일한 컬럼 수로 맞춤
        normalized_rows = []
        for row in rows:
            normalized_row = row[:max_cols]  # 필요한 만큼만 자르기
            while len(normalized_row) < max_cols:  # 부족한 컬럼은 빈 문자열로 채우기
                normalized_row.append('')
            normalized_rows.append(normalized_row)
        
        # 첫 번째 행을 헤더로 사용 (더 의미있는 헤더명 생성)
        headers = []
        for i in range(max_cols):
            if i < len(normalized_rows[0]):
                header_value = normalized_rows[0][i].strip()
                if header_value:
                    headers.append(header_value)
                else:
                    headers.append(f"컬럼 {i+1}")
            else:
                headers.append(f"컬럼 {i+1}")
        
        # 나머지 행들을 데이터로 사용
        data = []
        for row in normalized_rows[1:]:
            row_dict = {}
            for j, header in enumerate(headers):
                row_dict[header] = row[j] if j < len(row) else ''
            data.append(row_dict)
        
        if headers and data:
            return {
                'id': f'text_table_{len(rows)}',
                'title': f'텍스트 테이블 ({len(rows)}행, {len(headers)}열)',
                'data': data,
                'columns': headers
            }
        
    except Exception as e:
        print(f"테이블 생성 중 오류: {str(e)}")
    
    return None

def get_page_markdown(pdf_path, page_numbers):
    """지정된 페이지들의 마크다운을 추출"""
    try:
        import fitz  # PyMuPDF
        
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        
        # 페이지 번호 유효성 검사
        for page_num in page_numbers:
            if page_num < 1 or page_num > total_pages:
                return None, f"페이지 번호는 1부터 {total_pages}까지 가능합니다."
        
        # pymupdf4llm을 사용하여 전체 PDF를 마크다운으로 변환
        import pymupdf4llm
        full_md_text = pymupdf4llm.to_markdown(pdf_path)
        
        # 전체 마크다운을 페이지별로 분할
        # pymupdf4llm은 페이지 구분을 위해 특별한 마커를 사용할 수 있음
        # 일반적인 페이지 구분자들을 시도
        page_separators = [
            '\n\n---\n\n',  # 일반적인 페이지 구분자
            '\n\n***\n\n',  # 다른 구분자
            '\n\n---\n',    # 단순한 구분자
            '\n\n***\n',    # 단순한 구분자
        ]
        
        pages = [full_md_text]  # 기본값: 전체 텍스트
        
        for separator in page_separators:
            if separator in full_md_text:
                pages = full_md_text.split(separator)
                break
        
        # 지정된 페이지들의 내용만 추출
        selected_pages_content = []
        for page_num in page_numbers:
            if page_num <= len(pages):
                page_content = pages[page_num - 1].strip()
                if page_content:
                    selected_pages_content.append(f"# 페이지 {page_num}\n\n{page_content}")
            else:
                # 페이지가 분할되지 않은 경우, 전체 텍스트를 사용
                selected_pages_content.append(f"# 페이지 {page_num}\n\n{full_md_text}")
        
        # 모든 선택된 페이지의 내용을 결합
        md_text = '\n\n---\n\n'.join(selected_pages_content)
        
        doc.close()
        return md_text, None
        
    except Exception as e:
        return None, f"페이지 추출 중 오류: {str(e)}"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': '파일이 선택되지 않았습니다.'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '파일이 선택되지 않았습니다.'}), 400
    
    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'PDF 파일만 업로드 가능합니다.'}), 400
    
    # 페이지 번호 가져오기 (복수 페이지 지원)
    page_input = request.form.get('page_numbers', '').strip()
    if not page_input:
        return jsonify({'error': '페이지 번호를 입력해주세요.'}), 400
    
    # 페이지 번호 파싱 (쉼표, 공백, 하이픈으로 구분)
    page_numbers = parse_page_numbers(page_input)
    if not page_numbers:
        return jsonify({'error': '유효한 페이지 번호를 입력해주세요. (예: 1,2,3 또는 1-3)'}), 400
    
    try:
        # 임시 파일로 저장
        temp_filename = f"{uuid.uuid4()}.pdf"
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_filename)
        file.save(temp_path)
        
        # 지정된 페이지들의 마크다운 추출
        md_text, error = get_page_markdown(temp_path, page_numbers)
        if error:
            os.remove(temp_path)
            return jsonify({'error': error}), 400
        
        # 테이블 추출 (마크다운에서)
        tables = extract_tables_from_markdown(md_text)
        
        # 임시 파일 삭제
        os.remove(temp_path)
        
        return jsonify({
            'success': True,
            'markdown': md_text,
            'tables': tables,
            'filename': file.filename,
            'page_numbers': page_numbers,
            'page_input': page_input,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        
    except Exception as e:
        # 에러 발생 시 임시 파일 정리
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return jsonify({'error': f'파일 처리 중 오류가 발생했습니다: {str(e)}'}), 500

@app.route('/download/<filename>')
def download_file(filename):
    try:
        return send_file(filename, as_attachment=True)
    except Exception as e:
        return jsonify({'error': f'파일 다운로드 중 오류가 발생했습니다: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
