import { connect, type Config } from "@tursodatabase/serverless";

function getConfig(): Config {
  const url = process.env.TURSO_HERMES_DATA_DB_URL;
  const token = process.env.TURSO_HERMES_DATA_DB_TOKEN;

  if (!url || !token) {
    throw new Error(
      "Missing Turso credentials: TURSO_HERMES_DATA_DB_URL and TURSO_HERMES_DATA_DB_TOKEN must be set"
    );
  }

  return { url, authToken: token };
}

let _conn: ReturnType<typeof connect> | null = null;

function getConn() {
  if (!_conn) {
    _conn = connect(getConfig());
  }
  return _conn;
}

export interface Busca {
  id: number;
  nome: string;
  ativa: number;
  regiao: string;
  bairros: string | null;
  cidades: string | null;
  uf: string;
  tipos: string | null;
  modalidades: string | null;
  preco_min: number | null;
  preco_max: number | null;
  area_min: number | null;
  quartos_min: number | null;
  vagas_min: number | null;
  ultima_execucao: string | null;
  ultimo_total: number | null;
}

export interface Imovel {
  id: string;
  titulo: string;
  fonte: string;
  url: string;
  endereco: string | null;
  bairro: string;
  cidade: string;
  uf: string;
  tipo: string | null;
  modalidade: string;
  preco_venda: number | null;
  preco_aluguel: number | null;
  condominio: number | null;
  iptu: number | null;
  area_m2: number | null;
  quartos: number | null;
  banheiros: number | null;
  vagas: number | null;
  descricao: string | null;
  data_ultima_vista: string | null;
  data_primeira_vista: string | null;
  foto_url: string | null;
  latitude: number | null;
  longitude: number | null;
}

type Row = Record<string, string | number | null>;

function rowToImovel(row: Row): Imovel {
  return {
    id: String(row.id ?? ""),
    titulo: String(row.titulo ?? ""),
    fonte: String(row.fonte ?? ""),
    url: String(row.url ?? ""),
    endereco: row.endereco as string | null,
    bairro: String(row.bairro ?? ""),
    cidade: String(row.cidade ?? ""),
    uf: String(row.uf ?? ""),
    tipo: row.tipo as string | null,
    modalidade: String(row.modalidade ?? ""),
    preco_venda: row.preco_venda as number | null,
    preco_aluguel: row.preco_aluguel as number | null,
    condominio: row.condominio as number | null,
    iptu: row.iptu as number | null,
    area_m2: row.area_m2 as number | null,
    quartos: row.quartos as number | null,
    banheiros: row.banheiros as number | null,
    vagas: row.vagas as number | null,
    descricao: row.descricao as string | null,
    data_ultima_vista: row.data_ultima_vista as string | null,
    data_primeira_vista: row.data_primeira_vista as string | null,
    foto_url: row.foto_url as string | null,
    latitude: row.latitude as number | null,
    longitude: row.longitude as number | null,
  };
}

function rowToBusca(row: Row): Busca {
  return {
    id: Number(row.id),
    nome: String(row.nome ?? ""),
    ativa: Number(row.ativa ?? 0),
    regiao: String(row.regiao ?? ""),
    bairros: row.bairros as string | null,
    cidades: row.cidades as string | null,
    uf: String(row.uf ?? ""),
    tipos: row.tipos as string | null,
    modalidades: row.modalidades as string | null,
    preco_min: row.preco_min as number | null,
    preco_max: row.preco_max as number | null,
    area_min: row.area_min as number | null,
    quartos_min: row.quartos_min as number | null,
    vagas_min: row.vagas_min as number | null,
    ultima_execucao: row.ultima_execucao as string | null,
    ultimo_total: row.ultimo_total as number | null,
  };
}

export async function listBuscas(): Promise<Busca[]> {
  const conn = getConn();
  const rows = await conn.execute("SELECT * FROM buscas_watchdog ORDER BY nome");
  return rows.rows.map((r) => rowToBusca(r as unknown as Row));
}

export async function getBusca(id: number): Promise<Busca | null> {
  const conn = getConn();
  const rows = await conn.execute({
    sql: "SELECT * FROM buscas_watchdog WHERE id = ?",
    args: [id],
  });
  if (rows.rows.length === 0) return null;
  return rowToBusca(rows.rows[0] as unknown as Row);
}

export interface ImovelFilters {
  busca_id?: number;
  bairro?: string;
  tipo?: string;
  modalidade?: string;
  preco_max?: number;
  preco_min?: number;
  area_min?: number;
  quartos_min?: number;
  vagas_min?: number;
  cidade?: string;
  fonte?: string;
  limit?: number;
  offset?: number;
}

export async function listImoveis(filters: ImovelFilters = {}): Promise<{ imoveis: Imovel[]; total: number }> {
  const conn = getConn();
  const conditions: string[] = [];
  const args: (string | number)[] = [];

  if (filters.bairro) {
    conditions.push("bairro LIKE ?");
    args.push(`%${filters.bairro}%`);
  }
  if (filters.tipo) {
    conditions.push("tipo = ?");
    args.push(filters.tipo);
  }
  if (filters.modalidade) {
    conditions.push("modalidade = ?");
    args.push(filters.modalidade);
  }
  if (filters.preco_min !== undefined) {
    conditions.push("(preco_venda >= ? OR preco_aluguel >= ?)");
    args.push(filters.preco_min, filters.preco_min);
  }
  if (filters.preco_max !== undefined) {
    conditions.push("(preco_venda <= ? OR preco_aluguel <= ?)");
    args.push(filters.preco_max, filters.preco_max);
  }
  if (filters.area_min !== undefined) {
    conditions.push("area_m2 >= ?");
    args.push(filters.area_min);
  }
  if (filters.quartos_min !== undefined) {
    conditions.push("quartos >= ?");
    args.push(filters.quartos_min);
  }
  if (filters.vagas_min !== undefined) {
    conditions.push("vagas >= ?");
    args.push(filters.vagas_min);
  }
  if (filters.cidade) {
    conditions.push("cidade LIKE ?");
    args.push(`%${filters.cidade}%`);
  }
  if (filters.fonte) {
    conditions.push("fonte = ?");
    args.push(filters.fonte);
  }

  const where = conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";
  const limit = filters.limit ?? 50;
  const offset = filters.offset ?? 0;

  const [countResult, dataResult] = await conn.execute([
    { sql: `SELECT COUNT(*) as total FROM imoveis_watchdog ${where}`, args },
    {
      sql: `SELECT * FROM imoveis_watchdog ${where} ORDER BY data_ultima_vista DESC LIMIT ? OFFSET ?`,
      args: [...args, limit, offset],
    },
  ]);

  const total = Number((countResult.rows[0] as unknown as Row).total);
  const imoveis = dataResult.rows.map((r) => rowToImovel(r as unknown as Row));

  return { imoveis, total };
}

export async function getImoveisRecentes(limit: number = 20): Promise<Imovel[]> {
  const conn = getConn();
  const rows = await conn.execute({
    sql: "SELECT * FROM imoveis_watchdog ORDER BY data_primeira_vista DESC LIMIT ?",
    args: [limit],
  });
  return rows.rows.map((r) => rowToImovel(r as unknown as Row));
}

export async function getDistinctBairros(): Promise<string[]> {
  const conn = getConn();
  const rows = await conn.execute(
    "SELECT DISTINCT bairro FROM imoveis_watchdog WHERE bairro IS NOT NULL AND bairro != '' ORDER BY bairro"
  );
  return rows.rows.map((r) => String((r as unknown as Row).bairro));
}

export async function getDistinctTipos(): Promise<string[]> {
  const conn = getConn();
  const rows = await conn.execute(
    "SELECT DISTINCT tipo FROM imoveis_watchdog WHERE tipo IS NOT NULL AND tipo != '' ORDER BY tipo"
  );
  return rows.rows.map((r) => String((r as unknown as Row).tipo));
}

export async function getDistinctFontes(): Promise<string[]> {
  const conn = getConn();
  const rows = await conn.execute(
    "SELECT DISTINCT fonte FROM imoveis_watchdog WHERE fonte IS NOT NULL AND fonte != '' ORDER BY fonte"
  );
  return rows.rows.map((r) => String((r as unknown as Row).fonte));
}

export async function listBuscasComResultados(): Promise<(Busca & { resultado_count: number })[]> {
  const conn = getConn();
  const rows = await conn.execute(`
    SELECT b.*, COALESCE(r.resultado_count, 0) as resultado_count
    FROM buscas_watchdog b
    LEFT JOIN (
      SELECT busca_id, COUNT(*) as resultado_count
      FROM imoveis_watchdog
      GROUP BY busca_id
    ) r ON b.id = r.busca_id
    ORDER BY b.ultima_execucao DESC NULLS LAST, b.nome
  `);
  return rows.rows.map((r) => {
    const row = r as unknown as Row;
    return {
      ...rowToBusca(row),
      resultado_count: Number(row.resultado_count ?? 0),
    };
  });
}
