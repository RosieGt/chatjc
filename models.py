from extensions import db
from datetime import datetime

class Usuario(db.Model):
    __tablename__ = 'usuarios'
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha = db.Column(db.String(200), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # 'aluno' ou 'escola'
    banido = db.Column(db.Boolean, default=False)
    telefone = db.Column(db.String(20), nullable=True)
    
    
    def __repr__(self):
        return f'<Usuario {self.nome} ({self.tipo})>'

class Mensagem(db.Model):
    __tablename__ = 'mensagens'
    
    id = db.Column(db.Integer, primary_key=True)
    remetente_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    destinatario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    texto = db.Column(db.Text, nullable=False)
    arquivo_url = db.Column(db.String(300), nullable=True)
    data_envio = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Mensagem {self.id}>'

# Tabela intermediária que liga Alunos aos Grupos (Muitos-para-Muitos)
grupo_alunos = db.Table('grupo_alunos',
    db.Column('grupo_id', db.Integer, db.ForeignKey('grupos.id'), primary_key=True),
    db.Column('usuario_id', db.Integer, db.ForeignKey('usuarios.id'), primary_key=True)
)

class Grupo(db.Model):
    __tablename__ = 'grupos'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    alunos = db.relationship('Usuario', secondary=grupo_alunos, backref='grupos')    