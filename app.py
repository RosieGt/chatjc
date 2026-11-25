import os
import random
import threading
from datetime import datetime
from flask import Flask, flash, render_template, request, redirect, url_for, session
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from extensions import db
from models import db, Usuario, Mensagem, Grupo
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv()

app = Flask(__name__)
app.secret_key = "chave_secreta_super_segura"

# Configuração da URL do Banco de Dados (PostgreSQL / Supabase / Render)
database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("A variável DATABASE_URL não foi encontrada!")

if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}

db.init_app(app)

def enviar_email_async(destinatario, codigo):
    remetente = "jc.almeidagestaomonitoria@gmail.com"
    senha_app = "fbxiwikguycfatid"
    
    msg = MIMEMultipart()
    msg['From'] = remetente
    msg['To'] = destinatario
    msg['Subject'] = "Código de Verificação - Chat"
    
    corpo = f"Olá! Seu código de verificação para concluir o cadastro é: {codigo}"
    msg.attach(MIMEText(corpo, 'plain'))
    
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=10)
        server.starttls()
        server.login(remetente, senha_app)
        server.sendmail(remetente, destinatario, msg.as_string())
        server.quit()
    except Exception as e:
        print("Erro ao enviar e-mail em background:", e)

def enviar_email_verificacao(destinatario, codigo):
    t = threading.Thread(target=enviar_email_async, args=(destinatario, codigo))
    t.start()
    return True

# --- ROTAS PÚBLICAS E AUTENTICAÇÃO ---

@app.route("/")
def home():
    session.clear()
    return render_template("login.html")

@app.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "POST":
        etapa = request.form.get("etapa", "1")
        
        if etapa == "1":
            nome = request.form.get("nome")
            email = request.form.get("email")
            telefone = request.form.get("telefone")
            senha = request.form.get("senha")
            
            if Usuario.query.filter_by(email=email).first():
                return "Este e-mail já está cadastrado! <a href='/registro'>Voltar</a>"
            
            codigo_email = str(random.randint(1000, 9999))
            
            session['temp_cadastro'] = {
                'nome': nome,
                'email': email,
                'senha': senha,
                'telefone': telefone,
                'codigo': codigo_email
            }
            
            sucesso = enviar_email_verificacao(email, codigo_email)
            if not sucesso:
                return "Erro ao enviar o e-mail. Verifique suas configurações. <a href='/registro'>Voltar</a>"
            
            return render_template("verificar_sms.html", telefone=email)
            
        elif etapa == "2":
            codigo_digitado = request.form.get("codigo")
            dados = session.get('temp_cadastro')
            
            if not dados:
                return "Sessão expirada. <a href='/registro'>Refazer cadastro</a>"
                
            if codigo_digitado == dados['codigo']:
                novo_aluno = Usuario(
                    nome=dados['nome'],
                    email=dados['email'],
                    senha=dados['senha'],
                    telefone=dados['telefone'],
                    tipo='aluno'
                )
                db.session.add(novo_aluno)
                db.session.commit()
                
                session.pop('temp_cadastro', None)
                return "Cadastro realizado com sucesso! <a href='/'>Fazer Login</a>"
            else:
                return "Código inválido! <a href='/registro'>Tentar novamente</a>"
                
    return render_template("registro.html")

@app.route("/fazer-login", methods=["POST"])
def fazer_login():
    email = request.form.get("email")
    senha = request.form.get("senha")
    
    usuario = Usuario.query.filter_by(email=email, senha=senha).first()
    if not usuario:
        return "E-mail ou senha incorretos! <a href='/'>Tentar novamente</a>"
    if usuario.banido:
        return "Sua conta foi banida pela administração da escola."
        
    session["usuario_id"] = usuario.id
    session["tipo"] = usuario.tipo
    
    if usuario.tipo == "escola":
        return redirect(url_for('painel_admin'))
    elif usuario.tipo == "admin":
        return redirect(url_for('admin_painel'))
    else:
        return redirect(url_for('painel_aluno'))

# --- PAINEL SUPERUSUÁRIO (ESCOLA) ---

@app.route("/admin")
def painel_admin():
    if session.get("tipo") != "escola":
        return redirect(url_for('home'))
        
    termo = request.args.get("q", "")
    if termo:
        alunos = Usuario.query.filter(
            Usuario.tipo == "aluno",
            (Usuario.nome.ilike(f"%{termo}%")) | (Usuario.email.ilike(f"%{termo}%"))
        ).all()
    else:
        alunos = Usuario.query.filter_by(tipo="aluno").all()
        
    return render_template("admin.html", alunos=alunos, termo_busca=termo)

@app.route("/admin/enviar-geral", methods=["POST"])
def enviar_geral():
    if session.get("tipo") != "escola":
        return redirect(url_for('home'))
        
    texto = request.form.get("texto")
    escola = Usuario.query.get(session["usuario_id"])
    alunos = Usuario.query.filter_by(tipo="aluno", banido=False).all()
    
    for aluno in alunos:
        db.session.add(Mensagem(remetente_id=escola.id, destinatario_id=aluno.id, texto=texto))
    db.session.commit()
    return "Mensagem transmitida para todos! <a href='/admin'>Voltar</a>"

@app.route("/admin/alternar-ban/<int:usuario_id>")
def alternar_ban(usuario_id):
    if session.get("tipo") != "escola":
        return redirect(url_for('home'))
        
    aluno = Usuario.query.get_or_404(usuario_id)
    aluno.banido = not aluno.banido
    db.session.commit()
    return redirect(url_for('painel_admin'))

@app.route("/admin/chat/<int:aluno_id>")
def admin_chat_aluno(aluno_id):
    if session.get("tipo") != "escola":
        return redirect(url_for('home'))
        
    admin = Usuario.query.get(session["usuario_id"])
    aluno = Usuario.query.get_or_404(aluno_id)
    
    mensagens = Mensagem.query.filter(
        ((Mensagem.remetente_id == admin.id) & (Mensagem.destinatario_id == aluno.id)) |
        ((Mensagem.remetente_id == aluno.id) & (Mensagem.destinatario_id == admin.id))
    ).order_by(Mensagem.data_envio.asc()).all()
    
    return render_template("chat_individual.html", outro_usuario=aluno, mensagens=mensagens, usuario_atual_id=admin.id, session_tipo="escola")

# --- PAINEL ADMIN COMUM (WHATSAPP WEB) ---

@app.route("/admin/painel")
def admin_painel():
    if session.get("tipo") not in ["admin", "escola"]:
        return redirect(url_for('home'))

    alunos = []
    termo = request.args.get("busca")

    try:
        alunos_query = Usuario.query.filter_by(tipo='aluno')
        if termo:
            alunos_query = alunos_query.filter((Usuario.nome.ilike(f"%{termo}%")) | (Usuario.email.ilike(f"%{termo}%")))
        alunos = alunos_query.all()
    except Exception as e:
        print("Erro ao buscar alunos:", e)

    grupos = Grupo.query.all()

    aluno_id_ativo = request.args.get("aluno_id")
    grupo_id_ativo = request.args.get("grupo_id")
    
    aluno_ativo = db.session.get(Usuario, int(aluno_id_ativo)) if aluno_id_ativo else None
    grupo_ativo = db.session.get(Grupo, int(grupo_id_ativo)) if grupo_id_ativo else None
    
    lista_alunos_com_detalhes = []
    admin_atual_id = session["usuario_id"]
    
    admins_escola_ids = [u.id for u in Usuario.query.filter(Usuario.tipo.in_(["escola", "admin"])).all()]
    
    for aluno in alunos:
        ultima_msg_obj = Mensagem.query.filter(
            ((Mensagem.remetente_id == aluno.id) & (Mensagem.destinatario_id.in_(admins_escola_ids))) |
            ((Mensagem.remetente_id.in_(admins_escola_ids)) & (Mensagem.destinatario_id == aluno.id))
        ).order_by(Mensagem.data_envio.desc()).first()
        
        ultima_texto = ultima_msg_obj.texto if ultima_msg_obj else None
        if not ultima_texto and ultima_msg_obj and ultima_msg_obj.arquivo_url:
            ultima_texto = "[Arquivo anexado]"
            
        lista_alunos_com_detalhes.append({
            "aluno": aluno,
            "ultima_msg": ultima_texto,
            "ultima_data": ultima_msg_obj.data_envio if ultima_msg_obj else None
        })
        
    lista_alunos_com_detalhes.sort(
        key=lambda x: x["ultima_data"] if x["ultima_data"] else datetime.min,
        reverse=True
    )
    
    mensagens = []
    if aluno_ativo:
        mensagens = Mensagem.query.filter(
            ((Mensagem.remetente_id == aluno_ativo.id) & (Mensagem.destinatario_id.in_(admins_escola_ids))) |
            ((Mensagem.remetente_id.in_(admins_escola_ids)) & (Mensagem.destinatario_id == aluno_ativo.id))
        ).order_by(Mensagem.data_envio.asc()).all()

    return render_template(
        "admin_whatsapp.html",
        lista_alunos=lista_alunos_com_detalhes,
        alunos=alunos,
        grupos=grupos,
        aluno_ativo=aluno_ativo,
        grupo_ativo=grupo_ativo,
        mensagens=mensagens,
        admin_atual_id=admin_atual_id,
        termo_busca=termo
    )

@app.route("/admin/enviar", methods=["POST"])
def admin_enviar_mensagem():
    if session.get("tipo") not in ["admin", "escola"]:
        return redirect(url_for('home'))
        
    admin_id = session["usuario_id"]
    aluno_id = request.form.get("aluno_id")
    texto = request.form.get("texto", "")
    
    arquivo_url = None
    arquivo = request.files.get("arquivo")
    if arquivo and arquivo.filename != "":
        upload_folder = os.path.join("static", "uploads")
        os.makedirs(upload_folder, exist_ok=True)
        filename = secure_filename(arquivo.filename)
        caminho_completo = os.path.join(upload_folder, filename)
        arquivo.save(caminho_completo)
        arquivo_url = f"/static/uploads/{filename}"
    
    if texto or arquivo_url:
        nova_msg = Mensagem(
            remetente_id=admin_id,
            destinatario_id=aluno_id,
            texto=texto,
            arquivo_url=arquivo_url
        )
        db.session.add(nova_msg)
        db.session.commit()
        
    return redirect(url_for('admin_painel', aluno_id=aluno_id))

@app.route("/admin/criar-grupo", methods=["POST"])
def criar_grupo():
    nome_grupo = request.form.get("nome_grupo")
    alunos_ids = request.form.getlist("alunos_ids")
    
    if nome_grupo and alunos_ids:
        novo_grupo = Grupo(nome=nome_grupo)
        for a_id in alunos_ids:
            aluno = db.session.get(Usuario, int(a_id))
            if aluno:
                novo_grupo.alunos.append(aluno)
                
        db.session.add(novo_grupo)
        db.session.commit()
        
    return redirect(url_for("admin_painel"))

@app.route("/admin/enviar-grupo", methods=["POST"])
def enviar_grupo():
    arquivo_url = None
    texto = request.form.get("texto")
    grupo_id = request.form.get("grupo_id")
    
    file = request.files.get("arquivo")
    if file and file.filename != "":
        filename = secure_filename(file.filename)
        upload_folder = os.path.join('static', 'uploads')
        os.makedirs(upload_folder, exist_ok=True)
        
        filepath = os.path.join(upload_folder, filename)
        file.save(filepath)
        
        arquivo_url = url_for('static', filename=f'uploads/{filename}')

    grupo = db.session.get(Grupo, int(grupo_id))
    if grupo:
        admin_id = session.get("usuario_id") 
        
        for aluno in grupo.alunos:
            nova_msg = Mensagem(
                texto=texto,
                arquivo_url=arquivo_url,
                remetente_id=admin_id,
                destinatario_id=aluno.id
            )
            db.session.add(nova_msg)
        
        db.session.commit()
        flash(f"Mensagem enviada com sucesso para todos os alunos do grupo {grupo.nome}!", "success")
        
    return redirect(url_for("admin_painel", grupo_id=grupo_id))

@app.route("/admin/excluir-grupo/<int:grupo_id>", methods=["POST"])
def excluir_grupo(grupo_id):
    grupo = db.session.get(Grupo, grupo_id)
    if grupo:
        grupo.alunos.clear()
        db.session.delete(grupo)
        db.session.commit()
    return redirect(url_for("admin_painel"))

@app.route("/admin/editar-grupo/<int:grupo_id>", methods=["POST"])
def editar_grupo(grupo_id):
    grupo = db.session.get(Grupo, grupo_id)
    if grupo:
        novo_nome = request.form.get("nome_grupo")
        novos_alunos_ids = request.form.getlist("alunos_ids")
        
        if novo_nome:
            grupo.nome = novo_nome
            
        grupo.alunos.clear()
        for a_id in novos_alunos_ids:
            aluno = db.session.get(Usuario, int(a_id))
            if aluno:
                grupo.alunos.append(aluno)
                
        db.session.commit()
    return redirect(url_for("admin_painel", grupo_id=grupo_id))

@app.route("/admin/excluir-aluno/<int:usuario_id>", methods=["POST"])
def excluir_aluno(usuario_id):
    if session.get("tipo") != "escola":
        return redirect(url_for('home'))
        
    aluno = Usuario.query.get_or_404(usuario_id)
    
    Mensagem.query.filter(
        (Mensagem.remetente_id == aluno.id) | (Mensagem.destinatario_id == aluno.id)
    ).delete()
    
    db.session.delete(aluno)
    db.session.commit()
    
    flash(f"Aluno {aluno.nome} excluído com sucesso!", "success")
    return redirect(url_for('painel_admin'))

# --- PAINEL DO ALUNO ---

@app.route("/aluno")
def painel_aluno():
    if session.get("tipo") != "aluno":
        return redirect(url_for('home'))
        
    aluno = Usuario.query.get(session["usuario_id"])
    return render_template("aluno.html", aluno=aluno)

@app.route("/aluno/chat-escola")
def aluno_chat_escola():
    if session.get("tipo") != "aluno":
        return redirect(url_for('home'))
        
    aluno = Usuario.query.get(session["usuario_id"])
    
    admins_escola = Usuario.query.filter(Usuario.tipo.in_(["escola", "admin"])).all()
    admins_escola_ids = [u.id for u in admins_escola]
    
    if not admins_escola_ids:
        return "Nenhum administrador disponível."
        
    outro_usuario = admins_escola[0]
    
    mensagens = Mensagem.query.filter(
        ((Mensagem.remetente_id == aluno.id) & (Mensagem.destinatario_id.in_(admins_escola_ids))) |
        ((Mensagem.remetente_id.in_(admins_escola_ids)) & (Mensagem.destinatario_id == aluno.id))
    ).order_by(Mensagem.data_envio.asc()).all()
    
    return render_template("chat_individual.html", outro_usuario=outro_usuario, mensagens=mensagens, usuario_atual_id=aluno.id, session_tipo="aluno")

@app.route("/enviar-mensagem", methods=["POST"])
def enviar_mensagem():
    if "usuario_id" not in session:
        return redirect(url_for('home'))
        
    remetente_id = session["usuario_id"]
    destinatario_id = request.form.get("destinatario_id")
    texto = request.form.get("texto", "")
    
    arquivo_url = None
    arquivo = request.files.get("arquivo")
    if arquivo and arquivo.filename != "":
        upload_folder = os.path.join("static", "uploads")
        os.makedirs(upload_folder, exist_ok=True)
        filename = secure_filename(arquivo.filename)
        caminho_completo = os.path.join(upload_folder, filename)
        arquivo.save(caminho_completo)
        arquivo_url = f"/static/uploads/{filename}"
    
    if texto or arquivo_url:
        nova_msg = Mensagem(
            remetente_id=remetente_id,
            destinatario_id=destinatario_id,
            texto=texto,
            arquivo_url=arquivo_url
        )
        db.session.add(nova_msg)
        db.session.commit()
    
    if session["tipo"] == "escola" or session["tipo"] == "admin":
        return redirect(url_for('admin_painel', aluno_id=destinatario_id))
    else:
        return redirect(url_for('aluno_chat_escola'))

# --- INICIALIZAÇÃO DO BANCO E USUÁRIOS PADRÃO ---

with app.app_context():
    db.create_all()
    
    if not Usuario.query.filter_by(email="escola@chat.com").first():
        db.session.add(Usuario(
            nome="Administração da Escola",
            email="escola@chat.com",
            senha="admin123",
            tipo="escola",
            banido=False
        ))
        
    if not Usuario.query.filter_by(email="atendimento@chat.com").first():
        db.session.add(Usuario(
            nome="Secretaria / Atendimento",
            email="atendimento@chat.com",
            senha="admin123",
            tipo="admin",
            banido=False
        ))
        
    db.session.commit()

if __name__ == "__main__":
    app.run(debug=True)