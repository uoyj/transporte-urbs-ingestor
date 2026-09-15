from sqlalchemy import Column, Integer, String, Numeric, Text, ForeignKey, Index, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class Linha(Base):
    """Linha de ônibus da URBS."""
    __tablename__ = "linhas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    codigo = Column(String(20), nullable=False, unique=True, index=True)
    nome = Column(Text, nullable=False)
    origem = Column(Text)
    destino = Column(Text)
    cor = Column(String(7))  # hex color ex: "#FF0000"

    pontos = relationship("Ponto", back_populates="linha")


class Ponto(Base):
    """Ponto de parada da URBS."""
    __tablename__ = "pontos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    codigo = Column(String(20), nullable=False, unique=True, index=True)
    latitude = Column(Numeric(10, 8), nullable=False)
    longitude = Column(Numeric(11, 8), nullable=False)
    descricao = Column(Text)
    linha_id = Column(Integer, ForeignKey("linhas.id", ondelete="CASCADE"))

    linha = relationship("Linha", back_populates="pontos")
    horarios = relationship("Horario", back_populates="ponto")


class Horario(Base):
    """Horário de passagem em um ponto."""
    __tablename__ = "horarios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ponto_id = Column(Integer, ForeignKey("pontos.id", ondelete="CASCADE"))
    dia_semana = Column(String(10), nullable=False)  # ex: "2" para segunda
    hora = Column(String(8), nullable=False)  # formato "HH:MM"

    # Unique constraint para upsert idempotente (ON CONFLICT)
    __table_args__ = (
        UniqueConstraint("ponto_id", "dia_semana", "hora", name="uq_horarios_ponto_dia_hora"),
    )

    ponto = relationship("Ponto", back_populates="horarios")


# Índice para busca espacial rápida
Index("idx_pontos_lat_lng", Ponto.latitude, Ponto.longitude)