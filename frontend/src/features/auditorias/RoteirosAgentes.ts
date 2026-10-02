/**
 * Decisões internas de cada agente, para a tela "Fluxo dos agentes".
 *
 * Os ramos espelham o código: grafo (`backend/app/pipeline/graph.py`), nós (`nodes.py`, `arvore.py`,
 * `analista.py`), o Juiz (`analise/avaliacao.py`) e a revisão (`review/service.py`). Se uma regra
 * mudar lá, muda aqui também.
 */

/** Para onde um ramo leva: outro agente (chave de AGENTES) ou um ponto final. */
export const DESTINOS_FINAIS = {
  recusado: "Arquivo recusado",
  ignorada: "Linha ignorada",
  cancelado: "Nada é cobrado",
  classificado: "Classificado",
  aguardando_informacao: "Aguardando informação",
  revisao: "Revisão humana",
  inicio: "Volta ao começo do item",
  planilha: "Planilha final",
} as const;
export type DestinoFinal = keyof typeof DESTINOS_FINAIS;

export type Tom = "normal" | "atalho" | "desvio" | "fim" | "humano";

export type Ramo = {
  /** A condição, em linguagem simples ("se o item já foi aprovado antes"). */
  se: string;
  /** Agente seguinte (chave de AGENTES) ou ponto final (chave de DESTINOS_FINAIS); sem ele, o passo continua no mesmo agente. */
  vai?: string;
  tom?: Tom;
  /** Rótulo de um destaque da caixa (api/fluxo.py) que conta quantos itens seguiram por aqui. */
  conta?: string;
  /** Status final cujo total conta os itens deste ramo. */
  contaStatus?: string[];
};

/** `nota` em lista vira tópicos (ex.: os 5 alarmes do Identificador). */
export type Decisao = { pergunta: string; ramos: Ramo[]; nota?: string | string[] };

export type Roteiro = {
  numero: number;
  passos: string[];
  decisoes: Decisao[];
  /** Quando a IA entra (ou "nunca"). */
  ia: string;
};

export const ROTEIROS: Record<string, Roteiro> = {
  recepcionista: {
    numero: 1,
    passos: [
      "Abre o arquivo enviado (.xlsx, .xls ou .csv).",
      "Recusa planilhas com macros, por segurança.",
      "Liga cada coluna ao campo certo (descrição, NCM, GTIN, marca…).",
    ],
    ia: "Nunca.",
    decisoes: [
      {
        pergunta: "O arquivo abre e é seguro?",
        ramos: [
          { se: "sim", vai: "conferente" },
          { se: "tem macros ou está corrompido", vai: "recusado", tom: "fim" },
        ],
      },
    ],
  },
  conferente: {
    numero: 2,
    passos: [
      "Lê linha por linha.",
      "Anota NCM com formato estranho, GTIN inválido e itens duplicados.",
      "Guarda cada linha válida como uma ficha.",
    ],
    ia: "Nunca.",
    decisoes: [
      {
        pergunta: "A linha tem descrição?",
        ramos: [
          { se: "sim: vira ficha (com os problemas anotados)", vai: "orcamentista", conta: "Itens válidos" },
          { se: "não", vai: "ignorada", tom: "fim", conta: "Ignorados" },
        ],
        nota: "Um NCM errado não barra a linha: quem decide o código certo são os agentes seguintes.",
      },
    ],
  },
  orcamentista: {
    numero: 3,
    passos: [
      "Conta os itens que já estão no caderno de aprovados (não vão gastar IA).",
      "Conta as famílias de NCM que já têm parecer da lei.",
      "Estima o custo de IA em dólares e o tempo.",
    ],
    ia: "Nunca. Só faz contas.",
    decisoes: [
      {
        pergunta: "A planilha é grande?",
        ramos: [
          { se: "sim: sugere o modo lote (IA com 50% de desconto, resposta mais lenta)", vai: "voce" },
          { se: "não: sugere tempo real", vai: "voce" },
        ],
      },
    ],
  },
  voce: {
    numero: 4,
    passos: [
      "Vê a prévia de custo e tempo.",
      "Escolhe tempo real ou lote.",
      "Aperta “Confirmar e iniciar”. Nenhuma IA trabalha antes disso.",
    ],
    ia: "Nenhuma: é a trava humana antes de gastar.",
    decisoes: [
      {
        pergunta: "Confirma o custo?",
        ramos: [
          { se: "confirma e cabe no orçamento do mês", vai: "distribuidor", tom: "humano" },
          { se: "passa do orçamento do mês", vai: "cancelado", tom: "fim" },
          { se: "não confirma", vai: "cancelado", tom: "fim" },
        ],
      },
    ],
  },
  distribuidor: {
    numero: 5,
    passos: [
      "Separa as fichas em pacotes de 10.",
      "Põe os pacotes numa fila.",
      "4 mesas pegam pacotes ao mesmo tempo; quem termina pega o próximo.",
    ],
    ia: "Nunca.",
    decisoes: [
      {
        pergunta: "Qual o modo escolhido?",
        ramos: [
          { se: "tempo real: cada pergunta à IA é respondida na hora", vai: "arrumador" },
          { se: "lote: as perguntas à IA esperam a resposta do lote (minutos ou horas)", vai: "arrumador" },
        ],
      },
    ],
  },
  arrumador: {
    numero: 6,
    passos: [
      "Tira a marca da descrição (marca não muda imposto).",
      "Troca abreviações conhecidas (“refrig.” → refrigerante).",
      "Dá um palpite: produto ou serviço.",
    ],
    ia: "Só quando sobram 2 ou mais palavras desconhecidas (IA leve, só no modo tempo real).",
    decisoes: [
      {
        pergunta: "Sobraram 2 ou mais palavras que ninguém reconhece?",
        ramos: [
          { se: "não: a descrição já está legível", vai: "fiscal" },
          {
            se: "sim: pede à IA leve para decifrar as abreviações",
            vai: "fiscal",
            tom: "desvio",
            conta: "Pediram ajuda à IA para abreviações",
          },
        ],
        nota: "Se a IA falhar, segue com a melhor descrição que tem: a expansão é só uma ajuda para a busca.",
      },
    ],
  },
  fiscal: {
    numero: 7,
    passos: [
      "Procura o NCM/NBS do ERP na tabela oficial.",
      "Confere se tem todos os dígitos (com 7, testa o zero que o Excel apaga).",
      "Confere se vale na data da auditoria.",
    ],
    ia: "Nunca. E não julga se o código combina com a descrição: isso é com o Identificador.",
    decisoes: [
      {
        pergunta: "A tabela oficial e a lei estão importadas?",
        ramos: [
          { se: "sim: registra o raio-X do código do ERP", vai: "arquivista" },
          {
            se: "não: não há como conferir nem estudar",
            vai: "juiz",
            tom: "desvio",
            conta: "Base oficial incompleta",
          },
        ],
      },
    ],
  },
  arquivista: {
    numero: 8,
    passos: [
      "Procura a descrição arrumada no caderno de itens aprovados por pessoas nesta empresa.",
      "O código de barras só vale se a descrição também bater.",
    ],
    ia: "Nunca. Só aceita o que uma pessoa aprovou; palpite de IA não entra no caderno.",
    decisoes: [
      {
        pergunta: "Este item já foi aprovado por uma pessoa?",
        ramos: [
          {
            se: "sim: o NCM já é conhecido, pula a identificação",
            vai: "jurista",
            tom: "atalho",
            conta: "Achou no caderno (pula a identificação)",
          },
          { se: "não", vai: "pesquisador", conta: "Não achou" },
        ],
      },
    ],
  },
  pesquisador: {
    numero: 9,
    passos: [
      "Busca na tabela oficial pelas palavras e pelo sentido da descrição (busca local, grátis).",
      "Junta até 15 alternativas, incluindo o NCM do ERP e seus “irmãos”.",
      "Marca as que a lei cita pelo nome.",
    ],
    ia: "Nunca. A busca roda no próprio servidor.",
    decisoes: [
      {
        pergunta: "O NCM do ERP ficou em 1º lugar nas duas buscas, sem a lei apontar outro?",
        ramos: [
          {
            se: "sim: confirmado sem gastar com IA",
            vai: "jurista",
            tom: "atalho",
            conta: "Atalho: confirmados sem IA",
          },
          { se: "não, e há alternativas", vai: "identificador" },
          { se: "não achou nenhuma alternativa", vai: "navegador", tom: "desvio", conta: "Sem nenhuma alternativa" },
        ],
      },
    ],
  },
  identificador: {
    numero: 10,
    passos: [
      "A IA lê a descrição e as alternativas oficiais (prova de múltipla escolha).",
      "Escolhe o NCM, diz se o do ERP combinava e dá uma certeza de 0 a 100%.",
      "Se a IA inventar um código fora da lista, a resposta é descartada.",
    ],
    ia: "Sempre (uma chamada por item; itens iguais reaproveitam a resposta).",
    decisoes: [
      {
        pergunta: "Algum alarme tocou?",
        ramos: [
          { se: "nenhum: resposta aceita", vai: "jurista" },
          { se: "pelo menos um", vai: "segundo_parecer", tom: "desvio" },
          { se: "respondeu que nenhuma alternativa serve, ou a resposta foi descartada", vai: "navegador", tom: "desvio" },
        ],
        nota: [
          "Os 5 alarmes:",
          "certeza abaixo do limite da organização",
          "o NCM do ERP não combina com a descrição",
          "o ERP não trouxe um código válido",
          "a IA escolheu um código que as buscas quase não consideraram (abaixo do 10º lugar, com menos de 95%)",
          "a IA registrou dúvidas e ficou abaixo de 85%",
        ],
      },
    ],
  },
  segundo_parecer: {
    numero: 11,
    passos: [
      "Uma IA mais forte recebe o item, as alternativas, a resposta anterior e os alarmes.",
      "É instruída a não concordar por simpatia: refaz a análise.",
      "O NCM final é o dela; a certeza mistura 40% do Identificador e 60% dela.",
    ],
    ia: "Só quando toca um alarme.",
    decisoes: [
      {
        pergunta: "Achou um NCM entre as alternativas?",
        ramos: [
          { se: "sim (concordando ou corrigindo)", vai: "jurista" },
          { se: "nenhuma alternativa serve", vai: "navegador", tom: "desvio" },
        ],
      },
    ],
  },
  navegador: {
    numero: 12,
    passos: [
      "Desce pela árvore oficial: capítulo → posição → subposição → código.",
      "Em cada nível a IA só escolhe entre opções que existem: não há como inventar código.",
      "Se o capítulo não tiver código que sirva, tenta até mais 2 capítulos.",
    ],
    ia: "Só quando o item ficou sem NCM.",
    decisoes: [
      {
        pergunta: "Chegou a um código final?",
        ramos: [
          {
            se: "sim: sugere o código (o contador confirma depois)",
            vai: "jurista",
            conta: "Acharam um NCM sugerido na tabela",
          },
          { se: "não, mas o ERP tinha um NCM: ele fica como referência, não confirmado", vai: "jurista", tom: "desvio" },
          {
            se: "não: o item fica sem código",
            vai: "leitor",
            tom: "desvio",
            conta: "Ficaram sem código",
          },
        ],
        nota: "Sem código ainda dá para decidir pela operação (ex.: restaurante), por isso o item segue ao Leitor.",
      },
    ],
  },
  jurista: {
    numero: 13,
    passos: [
      "Lê a lei, a correlação oficial e a tabela cClassTrib para o NCM da família.",
      "Escreve hipóteses “se… então…” da mais benéfica à regra geral (000001).",
      "Lista as perguntas que decidem entre elas.",
    ],
    ia: "Uma vez por família (NCM + perfil da empresa + data), não por item.",
    decisoes: [
      {
        pergunta: "Esta família já tem parecer?",
        ramos: [
          {
            se: "sim: reaproveita, grátis",
            vai: "leitor",
            tom: "atalho",
          },
          {
            se: "outro item da mesma família está sendo estudado agora: espera e reaproveita",
            vai: "leitor",
            tom: "atalho",
          },
          { se: "não: estuda a lei agora", vai: "leitor" },
          { se: "o estudo falhou", vai: "juiz", tom: "desvio" },
        ],
      },
    ],
  },
  leitor: {
    numero: 14,
    passos: [
      "Pega as perguntas do Jurista e as dos regimes da operação da empresa.",
      "Pula o que já se sabe (dossiê da empresa, respostas anteriores).",
      "Procura o resto na descrição: o que está escrito vira fato; palpite vira só sugestão.",
    ],
    ia: "Só quando há fato a procurar que ainda não se sabe.",
    decisoes: [
      {
        pergunta: "Falta algum fato para decidir?",
        ramos: [
          { se: "não: não chama a IA", vai: "juiz" },
          { se: "sim: lê a descrição com a IA", vai: "juiz" },
        ],
        nota: "Suposição não vira fato: “MEDICAMENTO 500MG” não diz se está na lista da lei, então fica desconhecido.",
      },
    ],
  },
  juiz: {
    numero: 15,
    passos: [
      "Testa primeiro os regimes da operação (bares e restaurantes, manipulação), que valem sem NCM.",
      "Depois as hipóteses do Jurista, em ordem: fica com a primeira que todos os fatos confirmam.",
      "Compara com o que pessoas já decidiram para o mesmo código e ramo.",
      "Preenche o boletim de 10 notas e decide o destino.",
    ],
    ia: "Nunca. São regras fixas: a mesma entrada dá sempre o mesmo resultado.",
    decisoes: [
      {
        pergunta: "Para cada hipótese, em ordem: os fatos confirmam?",
        ramos: [
          { se: "um fato contradiz a condição: hipótese afastada, testa a próxima" },
          { se: "todos confirmam: hipótese escolhida, para de testar" },
          { se: "falta um fato e as respostas levam a enquadramentos diferentes: vira pergunta", vai: "secretario", tom: "desvio" },
        ],
      },
      {
        pergunta: "Como ficou o boletim?",
        ramos: [
          {
            se: "tudo OK",
            vai: "classificado",
            tom: "fim",
            contaStatus: ["classificado"],
          },
          {
            se: "falta informação",
            vai: "secretario",
            tom: "desvio",
            contaStatus: ["aguardando_informacao"],
          },
          {
            se: "dúvida no NCM ou algum aviso: contador",
            vai: "revisao",
            tom: "humano",
            contaStatus: ["revisao_contador"],
          },
          {
            se: "falha jurídica (regra, cClassTrib, fonte ou conflito): especialista",
            vai: "revisao",
            tom: "humano",
            contaStatus: ["revisao_especialista"],
          },
        ],
        nota: "Classificado com aprovação automática ligada já sai aprovado e vai direto à planilha final.",
      },
    ],
  },
  secretario: {
    numero: 16,
    passos: [
      "Junta perguntas iguais de vários itens (por categoria ou família).",
      "Mostra para cada resposta o que acontece (“se sim → alíquota zero”).",
      "Põe tudo na aba Perguntas.",
    ],
    ia: "Nunca.",
    decisoes: [
      {
        pergunta: "Alguém respondeu?",
        ramos: [
          { se: "sim: o item volta só ao Juiz, sem gastar IA", vai: "juiz", tom: "humano" },
          { se: "ainda não", vai: "aguardando_informacao", tom: "fim" },
        ],
        nota: "Uma resposta vale para o grupo inteiro: 50 itens iguais, 1 pergunta.",
      },
    ],
  },
  revisao: {
    numero: 17,
    passos: [
      "Contador: confere itens com dúvida no NCM ou com aviso.",
      "Especialista: decide conflitos jurídicos (lei × tabela oficial, imposto seletivo…).",
      "Toda aprovação vira memória: o caderno da empresa e as decisões anteriores do ramo.",
    ],
    ia: "Nenhuma: decisão humana.",
    decisoes: [
      {
        pergunta: "O que a pessoa decide?",
        ramos: [
          { se: "aprova", vai: "exportacao", tom: "humano" },
          { se: "corrige o NCM: o item é reanalisado com o código novo", vai: "inicio", tom: "desvio" },
          { se: "informa um fato: só o Juiz refaz a conta, sem IA", vai: "juiz", tom: "desvio" },
          { se: "define CST e cClassTrib à mão, com justificativa, e aprova", vai: "exportacao", tom: "humano" },
          { se: "rejeita: sai marcado como rejeitado", vai: "exportacao", tom: "fim" },
        ],
        nota: "A partir de 3 decisões iguais para o mesmo código e ramo, o Juiz passa a tratar o enquadramento como confirmado.",
      },
    ],
  },
  exportacao: {
    numero: 18,
    passos: [
      "Monta a planilha final com NCM, CST, cClassTrib e o fundamento legal de cada item.",
      "Marca o que foi aprovado, ajustado ou rejeitado.",
    ],
    ia: "Nunca.",
    decisoes: [
      {
        pergunta: "Pronto para o ERP?",
        ramos: [{ se: "sempre: baixe e reimporte no seu ERP", vai: "planilha", tom: "fim" }],
      },
    ],
  },
};
