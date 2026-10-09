"""Loopback-only HTTP UI. All browser mutations require a session CSRF token."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import mimetypes
import os
from pathlib import Path
import secrets
import sys
from urllib.parse import urlsplit,parse_qs,unquote
from .core import Workbench,dumps,loads
from .calculations import TEMPLATES,FIELDS
from . import ai

MAX_BODY=2*1024*1024

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,workbench,port=8788,web_dir=None):
        self.workbench=workbench;self.token=secrets.token_urlsafe(32)
        source=Path(__file__).resolve().parent.parent/'web'
        self.web_dir=Path(web_dir) if web_dir else source if source.is_dir() else Path(sys.prefix)/'share/optics-workbench/web'
        super().__init__(('127.0.0.1',port),Handler)

class Handler(BaseHTTPRequestHandler):
    server_version='OpticsWorkbench/0.4'
    def log_message(self,fmt,*args):
        # Avoid logging query terms, local paths, or user-provided document content.
        pass

    def send_data(self,status,data,content_type='application/json; charset=utf-8',attachment=False):
        body=data if isinstance(data,bytes) else dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if attachment:self.send_header('Content-Disposition','attachment; filename="optical-prototype.json"')
        self.end_headers();self.wfile.write(body)

    def guarded(self,mutation=False):
        port=self.server.server_port
        allowed={f'127.0.0.1:{port}',f'localhost:{port}'}
        host=self.headers.get('Host','')
        if host not in allowed:
            self.send_data(403,dict(error='只允许通过本机地址访问'));return False
        origin=self.headers.get('Origin')
        if origin and origin!=f'http://{host}':
            self.send_data(403,dict(error='拒绝跨站请求'));return False
        if self.headers.get('Sec-Fetch-Site')=='cross-site':
            self.send_data(403,dict(error='拒绝跨站请求'));return False
        if mutation and not hmac.compare_digest(self.headers.get('X-Workbench-Token',''),self.server.token):
            # Drain a small, bounded rejected JSON body before closing. On
            # Windows an unread POST body can otherwise reset the connection
            # before the browser receives the definite token rejection.
            try:
                length=int(self.headers.get('Content-Length','0'))
                if 0<length<=MAX_BODY:
                    self.connection.settimeout(3)
                    self.rfile.read(length)
            except (ValueError,OSError):pass
            self.send_data(403,dict(error='会话已失效，请刷新页面'));return False
        return True

    def do_GET(self):
        if not self.guarded():return
        try:
            u=urlsplit(self.path);path=unquote(u.path);args=parse_qs(u.query)
            q=lambda name,default='':args.get(name,[default])[0]
            w=self.server.workbench
            if path=='/api/bootstrap':result=dict(app_version='0.4.0',stats=w.stats(),templates=TEMPLATES,fields=FIELDS,projects=w.projects(),csrf_token=self.server.token)
            elif path=='/api/stats':result=w.stats()
            elif path=='/api/library':result=w.library(q('q'),q('status'),q('page',1))
            elif path.startswith('/api/library/'):result=w.document(path[len('/api/library/'):])
            elif path=='/api/components':result=w.components(q('kind'),q('q'))
            elif path=='/api/knowledge':result=w.knowledge(q('q'))
            elif path=='/api/evidence':result=w.search_evidence(q('q'),int(q('limit',8)))
            elif path.startswith('/api/knowledge/'):result=w.reference(path[len('/api/knowledge/'):])
            elif path=='/api/models':result=w.models(q('q'))
            elif path=='/api/projects':result=w.projects()
            elif path=='/api/ai/status':result=ai.status(w)
            elif path=='/api/color/cases':result=w.color_cases()
            elif path.startswith('/api/color/cases/'):result=w.color_case(path[len('/api/color/cases/'):])
            elif path.startswith('/api/projects/'):
                rest=path[len('/api/projects/'):]
                if rest.endswith('/export'):return self.send_data(200,w.export_project(rest[:-len('/export')]),attachment=True)
                if rest.endswith('/scene'):result=w.scene(rest[:-len('/scene')])
                elif rest.endswith('/color'):result=w.color_budget(rest[:-len('/color')])
                else:result=w.project(rest)
            elif path in ('/','/index.html','/app.js','/styles.css','/optical-view.js','/optical-view.css','/color-view.js','/color-view.css'):
                filename='index.html' if path=='/' else path[1:]
                target=self.server.web_dir/filename
                if not target.is_file():return self.send_data(404,dict(error='前端资源未安装'))
                return self.send_data(200,target.read_bytes(),(mimetypes.guess_type(filename)[0] or 'application/octet-stream')+'; charset=utf-8')
            else:return self.send_data(404,dict(error='路径不存在'))
            self.send_data(200,result)
        except (ValueError,TypeError,OverflowError,ZeroDivisionError) as e:self.send_data(400,dict(error=str(e)))
        except Exception:self.send_data(500,dict(error='本地服务错误，操作未完成'))

    def do_POST(self):
        if not self.guarded(mutation=True):return
        try:
            if self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':return self.send_data(415,dict(error='请求应为 JSON'))
            if self.headers.get('Transfer-Encoding'):return self.send_data(400,dict(error='不支持分块请求'))
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=MAX_BODY:return self.send_data(413,dict(error='请求体为空或超过 2 MiB'))
            data=loads(self.rfile.read(length).decode('utf-8'))
            if not isinstance(data,dict):raise ValueError('请求体应为对象')
            path=urlsplit(self.path).path;w=self.server.workbench
            if path=='/api/sync':result=w.sync()
            elif path=='/api/projects/new':result=w.new_project(data.get('template','dlp'),data.get('name'))
            elif path=='/api/projects':result=w.save_project(data)
            elif path=='/api/calculate':result=w.calculate(data)
            elif path=='/api/projects/import':result=w.import_project(data)
            elif path=='/api/scene/trace':result=w.preview_scene(data.get('scene'))
            elif path=='/api/scene/save':result=w.save_scene(data.get('project_id'),data.get('version'),data.get('scene'))
            elif path=='/api/design/apply':result=w.apply_design(data.get('project_id'),data.get('version'),scene=data.get('scene'),parameter_updates=data.get('parameter_updates'),note=data.get('note',''),color_budget=data.get('color_budget'))
            elif path=='/api/design/preview':result=w.preview_design(data.get('project_id'),data.get('version'),scene=data.get('scene'),parameter_updates=data.get('parameter_updates'),note=data.get('note',''),color_budget=data.get('color_budget'))
            elif path=='/api/design/chain-template':result=w.chain_template(data.get('parameters'),data.get('receiving_plane'),data.get('start_stage'))
            elif path=='/api/color/calculate':result=w.calculate_color(data.get('budget'),data.get('parameters'))
            elif path=='/api/color/save':result=w.save_color(data.get('project_id'),data.get('version'),data.get('budget'))
            elif path=='/api/ai/chat':result=ai.chat(w,data.get('project_id'),data.get('version'),data.get('message'),history=data.get('history'),preview=data.get('preview',False),evidence_ids=data.get('evidence_ids'))
            elif path=='/api/ai/apply':result=ai.apply_proposal(w,data.get('project_id'),data.get('version'),data.get('proposal_id'))
            else:return self.send_data(404,dict(error='路径不存在'))
            self.send_data(200,result)
        except ai.AIError as e:self.send_data(503,dict(error=str(e)))
        except (ValueError,TypeError,UnicodeError,OverflowError,ZeroDivisionError) as e:self.send_data(400,dict(error=str(e)))
        except Exception:self.send_data(500,dict(error='本地服务错误，操作未完成'))

def main():
    parser=argparse.ArgumentParser(description='Local optical parameter workbench')
    parser.add_argument('--config',default=os.environ.get('OPTICS_WORKBENCH_CONFIG'))
    parser.add_argument('--data-dir',default=os.environ.get('OPTICS_WORKBENCH_DATA'))
    parser.add_argument('--port',type=int,default=8788)
    args=parser.parse_args()
    try:server=Server(Workbench(args.config,args.data_dir),args.port)
    except (ValueError,OSError) as e:parser.exit(1,str(e)+'\n')
    print(f'Optics Workbench: http://127.0.0.1:{server.server_port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
