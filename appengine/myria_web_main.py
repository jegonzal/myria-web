from distutils.util import strtobool
import json
import logging
import os
from threading import Lock
import urllib

import jinja2

from clang_catalog import ClangCatalog
from clang_connection import ClangConnection
from myria_catalog import MyriaCatalog
import requests
import webapp2
from raco import RACompiler
from raco.myrial.exceptions import MyrialCompileException
from raco.myrial import parser as MyrialParser
from raco.myrial import interpreter as MyrialInterpreter
from raco.language.clang import CCAlgebra
from raco.language.grappalang import GrappaAlgebra
from raco.language.myrialang import (MyriaLeftDeepTreeAlgebra,
                                     MyriaHyperCubeAlgebra,
                                     compile_to_json)
from raco.language.logical import OptLogicalAlgebra
from raco.viz import get_dot
from raco.myrial.keywords import get_keywords
from examples import examples
from demo3_examples import demo3_examples
from pagination import Pagination, QUERIES_PER_PAGE

import myria


# We need a (global) lock on the Myrial parser because yacc is not Threadsafe.
# .. see uwescience/datalogcompiler#39
# ..    (https://github.com/uwescience/datalogcompiler/issues/39)
myrial_parser_lock = Lock()
myrial_parser = MyrialParser.Parser()


def is_small_dataset(d, cell_limit=0):
    """A dataset is small if we know its size and the size is below the
    specified cell limit. (Number of cells is # cols * # rows.)"""
    return (d['numTuples'] >= 0 and
            ((cell_limit == 0) or
            (len(d['schema']['columnNames']) * d['numTuples'] <= cell_limit)))

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader('templates'),
    extensions=['jinja2.ext.autoescape'],
    autoescape=True)
JINJA_ENVIRONMENT.tests["small_dataset"] = is_small_dataset

version_file_path = os.path.join(os.path.dirname(__file__), 'VERSION')
branch_file_path = os.path.join(os.path.dirname(__file__), 'BRANCH')

try:
    with open(version_file_path, 'r') as version_file:
        VERSION = version_file.read().strip()
except:
    VERSION = "commit version file not found"

try:
    with open(branch_file_path, 'r') as branch_file:
        BRANCH = branch_file.read().strip()
except:
    BRANCH = "branch file not found"


def get_plan(query, language, backend, plan_type, connection,
             multiway_join=False, push_sql=False):
    catalog = None
    if multiway_join:
        catalog = MyriaCatalog(connection)
        assert catalog.get_num_servers()
    # Fix up the language string
    if language is None:
        language = "datalog"
    language = language.strip().lower()

    if backend == "clang":
        catalog = ClangCatalog(connection)
        target_algebra = CCAlgebra('file')
    elif backend == "grappa":
        catalog = ClangCatalog(connection)
        target_algebra = GrappaAlgebra()
    elif multiway_join:
        catalog = MyriaCatalog(connection)
        target_algebra = MyriaHyperCubeAlgebra(catalog)
    else:
        catalog = MyriaCatalog(connection)
        target_algebra = MyriaLeftDeepTreeAlgebra()

    if language == "datalog":
        dlog = RACompiler()
        dlog.fromDatalog(query)
        if not dlog.logicalplan:
            raise SyntaxError("Unable to parse Datalog")

        if plan_type == 'logical':
            return dlog.logicalplan

        dlog.optimize(target=target_algebra)

        if plan_type == 'physical':
            return dlog.physicalplan
        else:
            raise NotImplementedError('Datalog plan type %s' % plan_type)
    elif language in ["myrial", "sql"]:
        # We need a (global) lock on the Myrial parser because yacc
        # .. is not Threadsafe and App Engine uses multiple threads.
        with myrial_parser_lock:
            parsed = myrial_parser.parse(query)
        processor = MyrialInterpreter.StatementProcessor(catalog)
        processor.evaluate(parsed)

        if plan_type == 'logical':
            return processor.get_physical_plan(target_alg=OptLogicalAlgebra())
        elif plan_type == 'physical':
            return processor.get_physical_plan(target_alg=target_algebra,
                                               push_sql=push_sql)
        else:
            raise NotImplementedError('Myria plan type %s' % plan_type)
    raise NotImplementedError('Language %s is not supported on %s'
                              % (language, backend))


def get_logical_plan(query, language, backend, connection, push_sql=False):
    return get_plan(query, language, backend, 'logical', connection,
                    push_sql=push_sql)


def get_physical_plan(query, language, backend, connection,
                      multiway_join=False, push_sql=False):
    return get_plan(query, language, backend, 'physical', connection,
                    multiway_join, push_sql=push_sql)


def format_rule(expressions):
    if isinstance(expressions, list):
        return "\n".join(["%s = %s" % e for e in expressions])
    return str(expressions)


def get_datasets(connection):
    if not connection:
        return []
    try:
        return connection.datasets()
    except myria.MyriaError:
        return []


class MyriaHandler(webapp2.RequestHandler):

    def get_boolean_request_param(self, name, default=False):
        """Fetch a request parameter with the specified name, and return it as
        a boolean value. Missing parameters default to False, unless the
        optional default parameter is provided.

        :param name: (string) the parameter to be decoded
        :param default: (bool) the value of the parameter if missing from
                        the request.
        """
        return bool(strtobool(self.request.get(name, str(default))))

    def handle_exception(self, exception, debug_mode):
        self.response.headers['Content-Type'] = 'text/plain'
        if isinstance(exception,
                      (ValueError, SyntaxError, MyrialCompileException)):
            self.response.status = 400
            msg = '{}: {}'.format(exception.__class__.__name__, exception)
        else:
            self.response.status = 500
            msg = ""
            if debug_mode:
                self.response.out.write(": \n\n")
                import traceback
                msg = traceback.format_exc()

        self.response.out.write(msg)


class RedirectToEditor(MyriaHandler):

    def get(self, query=None):
        if query is not None:
            self.redirect("/editor?query=%s" % urllib.quote(query, ''), True)
        else:
            self.redirect("/editor", True)


class MyriaPage(MyriaHandler):
    def get_connection_string(self):
        conn = self.app.myriaConnection
        hostname = self.app.myriahostname
        port = self.app.myriaport
        if not conn:
            connection_string = "unable to connect to %s:%d" % (hostname, port)
        else:
            try:
                workers = conn.workers()
                alive = conn.workers_alive()
                connection_string = "%s:%d [%d/%d]" %\
                    (hostname, port, len(alive), len(workers))
            except:
                connection_string = "error connecting to %s:%d" % (
                    hostname, port)
        return connection_string

    def base_template_vars(self):
        if self.app.ssl:
            uri_scheme = "https"
        else:
            uri_scheme = "http"
        return {'connectionString': self.get_connection_string(),
                'myriaConnection': "{s}://{h}:{p}".format(
                    s=uri_scheme, h=self.app.myriahostname,
                    p=self.app.myriaport),
                'clangConnection': "{h}:{p}".format(
                    h=self.app.clanghostname, p=self.app.clangport),
                'version': VERSION,
                'branch': BRANCH}


def nano_to_str(elapsed):
    if elapsed is None:
        return None
    s = elapsed / 1000000000.0
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    elapsed_str = ' %fs' % s
    if m:
        elapsed_str = '%dm ' % m + elapsed_str
    if h:
        elapsed_str = '%dh ' % h + elapsed_str
    if d:
        elapsed_str = '%dd ' % d + elapsed_str
    return elapsed_str


class Queries(MyriaPage):

    def get(self):
        conn = self.app.connection
        args = {a: self.request.get(a) for a in self.request.arguments()}

        try:
            result = conn.queries(limit=args.get("limit", QUERIES_PER_PAGE),
                                  min_id=args.get("min"),
                                  max_id=args.get("max"),
                                  q=args.get("q"))
        except myria.MyriaError:
            result = {'max': 0, 'min': 0, 'results': []}

        query_string = ''
        if 'q' in args:
            query_string = args['q'].strip()
            if not query_string:
                del args['q']
            else:
                args['q'] = query_string

        queries = result['results']

        for q in queries:
            q['elapsedStr'] = nano_to_str(q['elapsedNanos'])
            bootstrap_status = {
                'ERROR': 'danger',
                'KILLED': 'danger',
                'SUCCESS': 'success',
                'RUNNING': 'warning',
            }
            q['bootstrapStatus'] = bootstrap_status.get(q['status'], '')

        template_vars = self.base_template_vars()
        template_vars.update({'queries': queries})
        template_vars['myrialKeywords'] = get_keywords()
        template_vars['pagination'] = Pagination(args, result)
        template_vars['page_url'] = lambda largs: '{}?{}'.format(
            self.request.path, urllib.urlencode(largs))
        template_vars['query_string'] = query_string

        # Actually render the page: HTML content
        self.response.headers['Content-Type'] = 'text/html'
        # .. load and render the template
        template = JINJA_ENVIRONMENT.get_template('queries.html')
        self.response.out.write(template.render(template_vars))


class Profile(MyriaPage):

    def get(self):
        conn = self.app.myriaConnection
        query_id = self.request.get("queryId")
        query_plan = {}
        if query_id != '':
            try:
                query_plan = conn.get_query_status(query_id)
            except myria.MyriaError:
                pass

        template_vars = self.base_template_vars()
        template_vars['queryPlan'] = json.dumps(query_plan)
        template_vars['queryId'] = query_id

        # Actually render the page: HTML content
        self.response.headers['Content-Type'] = 'text/html'
        # .. load and render the template
        template = JINJA_ENVIRONMENT.get_template('visualization.html')
        self.response.out.write(template.render(template_vars))


class Datasets(MyriaPage):

    def get(self, connection_=None):
        template_vars = self.base_template_vars()

        # Actually render the page: HTML content
        self.response.headers['Content-Type'] = 'text/html'
        # .. load and render the template
        template = JINJA_ENVIRONMENT.get_template('datasets.html')
        self.response.out.write(template.render(template_vars))


class Examples(MyriaPage):

    def get(self):
        # Get the language
        language = self.request.get('language')
        if not language:
            # default to MyriaL
            language = 'myrial'
        else:
            language = language.strip().lower()
        # Is language recognized?

        example_set = self.request.get('subset') or 'default'
        if example_set == 'demo3':
            examples_to_use = demo3_examples
        else:
            examples_to_use = examples

        if language not in examples_to_use:
            self.response.headers['Content-Type'] = 'text/plain'
            self.response.status = 404
            self.response.write(
                'Error 404 (Not Found): language %s not found' % language)
            return
        # Return the objects as json
        self.response.headers['Content-Type'] = 'application/json'
        self.response.write(json.dumps(examples_to_use[language]))


class Editor(MyriaPage):

    def get(self):
        # Actually render the page: HTML content
        self.response.headers['Content-Type'] = 'text/html'
        template_vars = self.base_template_vars()
        template_vars['myrialKeywords'] = get_keywords()
        template_vars['subset'] = 'default'

        # .. load and render the template
        template = JINJA_ENVIRONMENT.get_template('editor.html')
        self.response.out.write(template.render(template_vars))


class Demo3(MyriaPage):

    def get(self):
        # Actually render the page: HTML content
        self.response.headers['Content-Type'] = 'text/html'
        template_vars = self.base_template_vars()
        template_vars['myrialKeywords'] = get_keywords()
        template_vars['subset'] = 'demo3'

        # .. load and render the template
        template = JINJA_ENVIRONMENT.get_template('editor.html')
        self.response.out.write(template.render(template_vars))


class Plan(MyriaHandler):

    def post(self):
        "The same as get(), here because there may be long programs"
        self.get()

    def get(self):
        self.response.headers.add_header("Access-Control-Allow-Origin", "*")
        query = self.request.get("query")
        language = self.request.get("language")
        backend = self.request.get("backend", "myria")

        if backend == "myria":
            conn = self.app.myriaConnection
        elif backend in ["clang", "grappa"]:
            conn = self.app.clangConnection

        try:
            plan = get_logical_plan(query, language, backend, conn)
        except (MyrialCompileException,
                MyrialInterpreter.NoSuchRelationException) as e:
            self.response.headers['Content-Type'] = 'text/plain'
            self.response.write(str(e))
            self.response.status = 400
            return

        self.response.headers['Content-Type'] = 'application/json'
        self.response.write(json.dumps(format_rule(plan)))


class Optimize(MyriaHandler):

    def get(self):
        self.response.headers.add_header("Access-Control-Allow-Origin", "*")
        query = self.request.get("query")
        language = self.request.get("language")
        backend = self.request.get("backend", "myria")
        multiway_join = json.loads(self.request.get("multiway_join", "false"))
        push_sql = self.get_boolean_request_param("push_sql")

        if backend == "myria":
            conn = self.app.myriaConnection
        elif backend in ["clang", "grappa"]:
            conn = self.app.clangConnection

        assert type(multiway_join) is bool
        try:
            optimized = get_physical_plan(
                query, language, backend, conn, multiway_join, push_sql)

        except MyrialInterpreter.NoSuchRelationException as e:
            self.response.headers['Content-Type'] = 'text/plain'
            self.response.write(
                "Error 400 (Bad Request): Relation %s not found" % str(e))
            self.response.status = 400
            return

        self.response.headers['Content-Type'] = 'application/json'
        self.response.write(json.dumps(format_rule(optimized)))

    def post(self):
        "The same as get(), here because there may be long programs"
        self.get()


class Compile(MyriaHandler):

    def get(self):
        self.response.headers.add_header("Access-Control-Allow-Origin", "*")
        query = self.request.get("query")
        language = self.request.get("language")
        backend = self.request.get("backend", "myria")
        profile = self.get_boolean_request_param("profile")
        multiway_join = self.get_boolean_request_param("multiway_join")
        push_sql = self.get_boolean_request_param("push_sql")
        if multiway_join == 'false':
            multiway_join = False

        if backend == "myria":
            conn = self.app.myriaConnection
        elif backend in ["clang", "grappa"]:
            conn = self.app.clangConnection

        cached_logicalplan = str(
            get_logical_plan(query, language, backend, conn,
                             push_sql=push_sql))

        # Generate physical plan
        physicalplan = get_physical_plan(query, language, backend, conn,
                                         multiway_join=multiway_join,
                                         push_sql=push_sql)
        try:
            if backend == "myria":
                compiled = compile_to_json(
                    query, cached_logicalplan, physicalplan, language)
            elif backend in ["clang", "grappa"]:
                compiled = conn.create_json(
                    query, cached_logicalplan, physicalplan)

            if profile:
                compiled['profilingMode'] = ["QUERY", "RESOURCE"]
            else:
                compiled['profilingMode'] = []
        except requests.ConnectionError:
            self.response.headers['Content-Type'] = 'text/plain'
            self.response.status = 503
            self.response.write(
                'Error 503 (Unavailable): Unable to connect to REST server')
            return

        self.response.headers['Content-Type'] = 'application/json'
        self.response.write(json.dumps(compiled))

    def post(self):
        "The same as get(), here because there may be long programs"
        self.get()


class Execute(MyriaHandler):

    def post(self):
        self.response.headers.add_header("Access-Control-Allow-Origin", "*")

        query = self.request.get("query")
        language = self.request.get("language")
        backend = self.request.get("backend", "myria")
        profile = self.get_boolean_request_param("profile")
        multiway_join = self.get_boolean_request_param("multiway_join")
        push_sql = self.get_boolean_request_param("push_sql")
        conn = self.app.myriaConnection
        if backend in ["clang", "grappa"]:
            conn = self.app.clangConnection

        cached_logicalplan = str(get_logical_plan(query, language, backend,
                                                  conn, push_sql=push_sql))

        # Generate physical plan
        physicalplan = get_physical_plan(
            query, language, backend, conn, multiway_join=multiway_join,
            push_sql=push_sql)

        try:
            if backend == "myria":
                # Get the Catalog needed to get schemas for compiling the query
                # .. and compile
                compiled = compile_to_json(
                    query, cached_logicalplan, physicalplan, language)
                if profile:
                    compiled['profilingMode'] = ["QUERY", "RESOURCE"]
                else:
                    compiled['profilingMode'] = []
                query_status = conn.submit_query(compiled)
                # Issue the query
                query_url = 'http://%s:%d/execute?query_id=%d' %\
                            (self.app.myriahostname, self.app.myriaport,
                             query_status['queryId'])
            elif backend in ["clang", "grappa"]:
                compiled = conn.create_execute_json(
                    cached_logicalplan, physicalplan, backend)
                query_status = conn.submit_query(compiled)
                query_url = 'http://%s:%d/query?qid=%d' %\
                            (self.app.clanghostname, self.app.clangport,
                             query_status['queryId'])
            self.response.status = 201
            self.response.headers['Content-Type'] = 'application/json'
            self.response.headers['Content-Location'] = query_url
            self.response.write(json.dumps(query_status))
            return
        except myria.MyriaError as e:
            self.response.headers['Content-Type'] = 'text/plain'
            self.response.status = 400
            self.response.write("Error 400 (Bad Request): %s" % str(e))
            return
        except requests.ConnectionError as e:
            self.response.headers['Content-Type'] = 'text/plain'
            self.response.status = 503
            self.response.write(
                'Error 503 (Unavailable): \
                 Unable to connect to REST server to issue query')
            return

    def get(self):
        self.response.headers.add_header("Access-Control-Allow-Origin", "*")

        query_id = self.request.get("queryId")
        backend = self.request.get("backend")
        conn = self.app.myriaConnection
        if backend in ["clang", "grappa"]:
            conn = self.app.clangConnection

        if not query_id:
            self.response.hpeaders['Content-Type'] = 'text/plain'
            self.response.status = 400
            self.response.write("Error 400 (Bad Request): missing query_id")
            return

        if backend == "myria":
            query_status = conn.get_query_status(query_id)
        else:
            query_status = conn.check_query(query_id)

        self.response.headers['Content-Type'] = 'application/json'
        self.response.write(json.dumps(query_status))


class Dot(MyriaHandler):

    def get(self):
        self.response.headers.add_header("Access-Control-Allow-Origin", "*")
        query = self.request.get("query")
        language = self.request.get("language")
        plan_type = self.request.get("type")
        backend = self.request.get("backend", "myria")
        multiway_join = self.get_boolean_request_param("multiway_join")
        push_sql = self.get_boolean_request_param("push_sql")

        if multiway_join == 'false':
            multiway_join = False

        if backend == "myria":
            conn = self.app.myriaConnection
        elif backend in ["clang", "grappa"]:
            conn = self.app.clangConnection

        plan = get_plan(query, language, backend, plan_type, conn,
                        multiway_join=multiway_join, push_sql=push_sql)

        self.response.headers['Content-Type'] = 'text/plain'
        self.response.write(get_dot(plan))

    def post(self):
        "The same as get(), here because there may be long programs"
        self.get()


class Application(webapp2.WSGIApplication):
    def __init__(self, debug=True,
                 hostname='rest.myria.cs.washington.edu',
                 port=1776, ssl=True):
        routes = [
            ('/', RedirectToEditor),
            ('/editor', Editor),
            ('/queries', Queries),
            ('/profile', Profile),
            ('/datasets', Datasets),
            ('/plan', Plan),
            ('/optimize', Optimize),
            ('/compile', Compile),
            ('/execute', Execute),
            ('/dot', Dot),
            ('/examples', Examples),
            ('/demo3', Demo3)
        ]

        # Connection to Myria. Thread-safe
        self.myriaConnection = myria.MyriaConnection(hostname=hostname,
                                                     port=port, ssl=ssl)
        self.myriahostname = hostname
        self.myriaport = port

        self.clanghostname = 'localhost'
        self.clangport = 1337
        self.clangConnection = ClangConnection(self.clanghostname,
                                               self.clangport)
        self.ssl = ssl

        # Quiet logging for production
        logging.getLogger().setLevel(logging.WARN)

        webapp2.WSGIApplication.__init__(
            self, routes, debug=debug, config=None)

# app = Application(hostname='localhost', port=8753, ssl=False)
app = Application()
