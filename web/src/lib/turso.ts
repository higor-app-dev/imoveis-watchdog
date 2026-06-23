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

export interface ImovelFilters {
  id?: string;
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
  sort?: "data" | "preco" | "area";
  order?: "asc" | "desc";
}

// --- Raw Turso REST API via fetch ---
// Avoids @tursodatabase/serverless SDK compatibility issues

function getUrl(): string {
  const url = process.env.TURSO_HERMES_DATA_DB_URL;
  if (!url) throw new Error("Missing TURSO_HERMES_DATA_DB_URL");
  return url;
}

function getToken(): string {
  const token = process.env.TURSO_HERMES_DATA_DB_TOKEN;
  if (!token) throw new Error("Missing TURSO_HERMES_DATA_DB_TOKEN");
  return token;
}

type Row = Record<string, unknown>;

async function query(sql: string, args: (string | number)[] = []): Promise<Row[]> {
  const stmt: Record<string, unknown> = { sql };
  if (args.length > 0) {
    stmt.args = args.map((a) => ({ type: typeof a === "number" ? "integer" : "text", value: String(a) }));
  }

  const body = JSON.stringify({ requests: [{ type: "execute", stmt }] });
  const resp = await fetch(getUrl() + "/v2/pipeline", {
    method: "POST",
    headers: {
      Authorization: "Bearer " + getToken(),
      "Content-Type": "application/json",
    },
    body,
  });

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Turso error (${resp.status}): ${text.substring(0, 200)}`);
  }

  const data = (await resp.json()) as {
    results: [{ response: { result: { cols: { name: string }[]; rows: { type: string; value?: string | number }[][] } } }];
  };
  const result = data.results[0].response.result;
  const cols = result.cols.map((c) => c.name);

  return result.rows.map((row) => {
    const obj: Row = {};
    row.forEach((cell, i) => {
      if (cell.type === "null") {
        obj[cols[i]] = null;
      } else {
        obj[cols[i]] = cell.value ?? null;
      }
    });
    return obj;
  });
}

function toImovel(r: Row): Imovel {
  return {
    id: String(r.id ?? ""),
    titulo: String(r.titulo ?? ""),
    fonte: String(r.fonte ?? ""),
    url: String(r.url ?? ""),
    endereco: (r.endereco as string | null) ?? null,
    bairro: String(r.bairro ?? ""),
    cidade: String(r.cidade ?? ""),
    uf: String(r.uf ?? ""),
    tipo: (r.tipo as string | null) ?? null,
    modalidade: String(r.modalidade ?? ""),
    preco_venda: (r.preco_venda as number | null) ?? null,
    preco_aluguel: (r.preco_aluguel as number | null) ?? null,
    condominio: (r.condominio as number | null) ?? null,
    iptu: (r.iptu as number | null) ?? null,
    area_m2: (r.area_m2 as number | null) ?? null,
    quartos: (r.quartos as number | null) ?? null,
    banheiros: (r.banheiros as number | null) ?? null,
    vagas: (r.vagas as number | null) ?? null,
    descricao: (r.descricao as string | null) ?? null,
    data_ultima_vista: (r.data_ultima_vista as string | null) ?? null,
    data_primeira_vista: (r.data_primeira_vista as string | null) ?? null,
    foto_url: (r.foto_url as string | null) ?? null,
    latitude: (r.latitude as number | null) ?? null,
    longitude: (r.longitude as number | null) ?? null,
  };
}

function toBusca(r: Row): Busca {
  return {
    id: Number(r.id),
    nome: String(r.nome ?? ""),
    ativa: Number(r.ativa ?? 0),
    regiao: String(r.regiao ?? ""),
    bairros: (r.bairros as string | null) ?? null,
    cidades: (r.cidades as string | null) ?? null,
    uf: String(r.uf ?? ""),
    tipos: (r.tipos as string | null) ?? null,
    modalidades: (r.modalidades as string | null) ?? null,
    preco_min: (r.preco_min as number | null) ?? null,
    preco_max: (r.preco_max as number | null) ?? null,
    area_min: (r.area_min as number | null) ?? null,
    quartos_min: (r.quartos_min as number | null) ?? null,
    vagas_min: (r.vagas_min as number | null) ?? null,
    ultima_execucao: (r.ultima_execucao as string | null) ?? null,
    ultimo_total: (r.ultimo_total as number | null) ?? null,
  };
}

// --- Public API ---

export async function listBuscas(): Promise<Busca[]> {
  const rows = await query("SELECT * FROM buscas_watchdog ORDER BY nome");
  return rows.map(toBusca);
}

export async function getBusca(id: number): Promise<Busca | null> {
  const rows = await query("SELECT * FROM buscas_watchdog WHERE id = ?", [id]);
  return rows.length > 0 ? toBusca(rows[0]) : null;
}

export async function listImoveis(filters: ImovelFilters = {}): Promise<{ imoveis: Imovel[]; total: number }> {
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
  if (filters.id) {
    conditions.push("id = ?");
    args.push(filters.id);
  }
  if (filters.fonte) {
    conditions.push("fonte = ?");
    args.push(filters.fonte);
  }

  const where = conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";
  const limit = filters.limit ?? 50;
  const offset = filters.offset ?? 0;

  // Build ORDER BY
  const sortField = filters.sort ?? "data";
  const sortOrder = filters.order ?? "desc";
  const orderMap: Record<string, string> = {
    data: "data_primeira_vista",
    preco: "COALESCE(preco_venda, 999999999)",
    area: "COALESCE(area_m2, 0)",
  };
  const orderCol = orderMap[sortField] ?? "data_primeira_vista";
  const orderDir = sortOrder === "asc" ? "ASC" : "DESC";

  const [countRows, dataRows] = await Promise.all([
    query(`SELECT COUNT(*) as total FROM imoveis_watchdog ${where}`, args),
    query(
      `SELECT * FROM imoveis_watchdog ${where} ORDER BY ${orderCol} ${orderDir} LIMIT ? OFFSET ?`,
      [...args, limit, offset]
    ),
  ]);

  const total = Number(countRows[0].total);
  return { imoveis: dataRows.map(toImovel), total };
}

export async function getImoveisRecentes(limit = 20): Promise<Imovel[]> {
  const rows = await query(
    "SELECT * FROM imoveis_watchdog ORDER BY data_primeira_vista DESC LIMIT ?",
    [limit]
  );
  return rows.map(toImovel);
}

export async function getDistinctBairros(): Promise<string[]> {
  const rows = await query(
    "SELECT DISTINCT bairro FROM imoveis_watchdog WHERE bairro IS NOT NULL AND bairro != '' ORDER BY bairro"
  );
  return rows.map((r) => String(r.bairro ?? ""));
}

export async function getDistinctTipos(): Promise<string[]> {
  const rows = await query(
    "SELECT DISTINCT tipo FROM imoveis_watchdog WHERE tipo IS NOT NULL AND tipo != '' ORDER BY tipo"
  );
  return rows.map((r) => String(r.tipo ?? ""));
}

export async function getDistinctFontes(): Promise<string[]> {
  const rows = await query(
    "SELECT DISTINCT fonte FROM imoveis_watchdog WHERE fonte IS NOT NULL AND fonte != '' ORDER BY fonte"
  );
  return rows.map((r) => String(r.fonte ?? ""));
}

export async function listBuscasComResultados(): Promise<(Busca & { resultado_count: number })[]> {
  const totalRows = await query("SELECT COUNT(*) as total FROM imoveis_watchdog");
  const total = Number(totalRows[0].total ?? 0);
  const buscas = await listBuscas();
  return buscas.map((b) => ({ ...b, resultado_count: total }));
}
