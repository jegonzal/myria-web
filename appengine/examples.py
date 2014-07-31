import os

# Examples is a dictionary from language -> [pairs]. Each pair is (Label, Code).
datalog_examples = [
  ('Filter', '''A(x) :- R(x,3)'''),
  ('Join and filter', '''A(x) :- R(x,y), S(y,z,4), z<3'''),
  ('Self-join', '''A(x,z) :- R(x,y), R(y,z)'''),
  ('Triangles', '''A(x,y,z) :- R(x,y), S(y,z), T(z,x)'''),
  ('Cross Product', '''A(x,z) :- S(x), T(z)'''),
  ('Two cycles', 'A(x,z) :- R(x,y), S(y,a,z), T(z,b,x), W(a,b)'),
  ('Two Chained Rules', 'A(x,z) :- R(x,y,z).\nB(w) :- A(3,w)'),
  ('Two Independent Rules', 'A(x,z) :- R(x,y,z).\nB(w) :- C(3,w)'),
  ('Project TwitterK', 'JustX(x) :- TwitterK(x,y)'),
  ('Self Join TwitterK', 'SelfJoin(x,z) :- TwitterK(x,y), TwitterK(y,z)'),
  ('In Degrees from TwitterK', 'InDegree(x, COUNT(y)) :- TwitterK(x,y)'),
  ('Two Hops Count in TwitterK', 'TwoHopsCountK(x,z,COUNT(y)) :- TwitterK(x,y), TwitterK(y,z)'),
  ('Triangles TwitterK', 'Triangles(x,y,z) :- TwitterK(x,y), TwitterK(y,z), TwitterK(z,x)'),
  ('NCCDC Filtered to Attack Window', '''attackwindow(src, dst, time) :-
    nccdc(src,dst,proto,time, x, y, z)
    , time > 1366475761
    , time < 1366475821'''),
  ('NCCDC DDOS Victims', '''InDegree(dst, count(time)) :- nccdc(src, dst, prot, time, x, y, z).
Victim(dst) :- InDegree(dst, cnt), cnt > 10000'''),
  ('SP2Bench Q10', '''Q10(subject, predicate) :-
    sp2bench_1m(subject, predicate, 'person:Paul_Erdoes')'''),
  ('SP2Bench Q3a', '''Q3a(article) :- sp2bench_1m(article, 'rdf:type', 'bench:Article')
              , sp2bench_1m(article, 'swrc:pages', value)'''),
  ('SP2Bench Q1', '''Q1(yr) :- sp2bench_1m(journal, 'rdf:type', 'bench:Journal')
        , sp2bench_1m(journal, 'dc:title', 'Journal 1 (1940)')
        , sp2bench_1m(journal, 'dcterms:issued', yr)''')
]


def get_example(name):
    path = os.path.join(os.path.dirname(__file__),
                    'examples/{}'.format(name))
    with open(path) as fh:
        return fh.read().strip()


justx = '''T1 = scan(TwitterK);
T2 = [from T1 emit $0 as x];
store(T2, JustX);'''

twohops = '''T1 = scan(TwitterK);
T2 = scan(TwitterK);
Joined = [from T1, T2
          where T1.$1 = T2.$0
          emit T1.$0 as src, T1.$1 as link, T2.$1 as dst];
store(Joined, TwoHopsInTwitter);'''

profiling = '''P = scan(public:logs:Profiling);
Agg = [from P emit worker_id() as workerId, count(*) as numProfilings];
store(Agg, NumProfilings);'''

phytoplankton = '''OppData = scan(armbrustlab:seaflow:all_opp_v3);
VctData = scan(armbrustlab:seaflow:all_vct);

OppWithPop = select opp.*, vct.pop
             from OppData as opp,
                  VctData as vct
             where opp.Cruise = vct.Cruise
               and opp.Day = vct.Day
               and opp.File_Id = vct.File_Id
               and opp.Cell_Id = vct.Cell_Id;

PlanktonCount = select Cruise, count(*) as Phytoplankton
                from OppWithPop
                where pop != "beads" and pop != "noise"
                  and fsc_small > 10000;

store(PlanktonCount, public:demo:PlanktonCount);'''

sigma_clipping_naive = """Good = scan(public:adhoc:sc_points);

-- number of allowed standard deviations
const Nstd: 2;

do
    stats = [from Good emit avg(v) AS mean, stdev(v) AS std];
    NewBad = [from Good, stats where abs(Good.v - mean) > Nstd * std
              emit Good.*];
    Good = diff(Good, NewBad);
    continue = [from NewBad emit count(NewBad.v) > 0];
while continue;

store(Good, OUTPUT);
"""

plum_tx = '''-- find transactions involving Plum market
TX = scan(txdetail);
HD = scan(txheader);

Plum_TX = [from TX, HD
           where TX.TxHeaderID=HD.TxHeaderID and
                 HD.RetailerID=114146
           emit TX.TxHeaderID as header_id,
                TX.ProductID as product_id];

store(Plum_TX, plum_tx);
'''

frequent_pairs = '''const SUPPORT: 5;

plum_tx = Scan(plum_tx);
Pairs = [from plum_tx as b1, plum_tx as b2
        where b1.header_id=b2.header_id
               and b1.product_id > b2.product_id
         emit b1.product_id as item1,
              b2.product_id as item2,
              count(b1.header_id) as cnt];
FreqPairs = [from Pairs where cnt > SUPPORT emit *];

Store(FreqPairs, plum_frequent_item_pairs);
'''

myria_examples = [
    ('Find transactions involving Plum Market', plum_tx),
    ('Find frequently item pairs for Plum Market', frequent_pairs),
]

sql_examples = [
    ('JustX', '''JustX = SELECT $0 AS x FROM SCAN(TwitterK) AS Twitter;

store(JustX, public:adhoc:JustX);'''),
    ('InDegree', '''InDegree = SELECT $0, COUNT($1) FROM SCAN(TwitterK) AS Twitter;

store(InDegree, public:adhoc:InDegree);'''),
]

examples = { 'datalog' : [],
             'myrial' : myria_examples,
             'sql' : [] }
