# ADR-005: Asset, ContentUnit, and Sample are distinct

Status: Accepted

An Asset is immutable physical content; a ContentUnit is an addressable portion; a Sample is a logical training example. Keeping them separate avoids treating every file as one sample, supports multimodal relationships, and lets dataset versions change labels/splits without copying bytes.
