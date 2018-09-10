# -*- coding: utf-8 -*-
import rdflib
import RDFClosure as owl_rl
if owl_rl.json_ld_available:
    import rdflib_jsonld
from pyshacl.inference import CustomRDFSSemantics, CustomRDFSOWLRLSemantics
from pyshacl.shape import find_shapes
from pyshacl.consts import RDF_type, SH_conforms, \
    SH_result, SH_ValidationReport
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


class Validator(object):
    @classmethod
    def _load_default_options(cls, options_dict):
        options_dict.setdefault('inference', 'none')
        options_dict.setdefault('abort_on_error', False)

    @classmethod
    def _run_pre_inference(cls, target_graph, inference_option):
        try:
            if inference_option == 'rdfs':
                inferencer = owl_rl.DeductiveClosure(CustomRDFSSemantics)
            elif inference_option == 'owlrl':
                inferencer = owl_rl.DeductiveClosure(owl_rl.OWLRL_Semantics)
            elif inference_option == 'both' or inference_option == 'all'\
                    or inference_option == 'rdfsowlrl':
                inferencer = owl_rl.DeductiveClosure(CustomRDFSOWLRLSemantics)
            else:
                raise RuntimeError(
                    "Don't know how to do '{}' type inferencing."
                    .format(inference_option))
        except Exception as e:
            log.error("Error during creation of OWL-RL Deductive Closure")
            raise e
        try:
            inferencer.expand(target_graph)
        except Exception as e:
            log.error("Error while running OWL-RL Deductive Closure")
            raise e

    @classmethod
    def create_validation_report(cls, conforms, results):
        v_text = "Validation Report\nConforms: {}\n".format(str(conforms))
        result_len = len(results)
        if not conforms:
            assert result_len > 0, \
                "A Non-Conformant Validation Report must have at least one result."
        if result_len > 0:
            v_text += "Results ({}):\n".format(str(result_len))
        vg = rdflib.Graph()
        vr = rdflib.BNode()
        vg.add((vr, RDF_type, SH_ValidationReport))
        vg.add((vr, SH_conforms, rdflib.Literal(conforms)))
        for result in iter(results):
            _d, _bn, _tr = result
            v_text += _d
            vg.add((vr, SH_result, _bn))
            for tr in iter(_tr):
                vg.add(tr)
        log.info(v_text)
        return vg

    @classmethod
    def clone_graph(cls, source_graph, identifier=None):
        """

        :param source_graph:
        :type source_graph: rdflib.Graph
        :param identifier:
        :type identifier: str | None
        :return:
        """
        g = rdflib.Graph(identifier=identifier)
        for t in iter(source_graph):
            g.add(t)
        return g

    def __init__(self, target_graph, *args,
                 shacl_graph=None, options=None, **kwargs):
        if options is None:
            options = {}
        self._load_default_options(options)
        self.options = options
        assert isinstance(target_graph, rdflib.Graph),\
            "target_graph must be a rdflib Graph object"
        self.target_graph = target_graph
        if shacl_graph is None:
            shacl_graph = self.clone_graph(target_graph, 'shacl')
        assert isinstance(shacl_graph, rdflib.Graph),\
            "shacl_graph must be a rdflib Graph object"
        self.shacl_graph = shacl_graph

    def run(self):
        inference_option = self.options.get('inference', 'none')
        if inference_option and str(inference_option) != "none":
            self._run_pre_inference(self.target_graph, inference_option)
        shapes = find_shapes(self.shacl_graph)
        reports = []
        non_conformant = False
        for s in shapes:
            _is_conform, _reports = s.validate(self.target_graph)
            non_conformant = non_conformant or (not _is_conform)
            reports.extend(_reports)
        v_report = self.create_validation_report((not non_conformant), reports)
        return (not non_conformant), v_report


# TODO: check out rdflib.util.guess_format() for format. I think it works well except for perhaps JSON-LD
def _load_into_graph(target, rdf_format=None):
    if isinstance(target, rdflib.Graph):
        return target
    target_is_file = False
    target_is_text = False
    if isinstance(target, str):
        if target.startswith('file://'):
            target_is_file = True
            target = target[7:]
        elif len(target) < 240:
            if target.endswith('.ttl'):
                target_is_file = True
                rdf_format = rdf_format or 'turtle'
            if target.endswith('.nt'):
                target_is_file = True
                rdf_format = rdf_format or 'nt'
            elif target.endswith('.xml'):
                target_is_file = True
                rdf_format = rdf_format or 'xml'
            elif target.endswith('.json'):
                target_is_file = True
                rdf_format = rdf_format or 'json-ld'
        if not target_is_file:
            target_is_text = True
    else:
        raise RuntimeError("Cannot determine the format of the input graph")
    g = rdflib.Graph()
    if target_is_file:
        import os
        file_name = os.path.abspath(target)
        with open(file_name, mode='rb') as file:
            g.parse(source=None, publicID=None, format=rdf_format,
                    location=None, file=file)
    elif target_is_text:
        g.parse(data=target, format=rdf_format)
    return g


def validate(target_graph, *args, shacl_graph=None, inference=None, abort_on_error=False, **kwargs):
    """
    :param target_graph:
    :type target_graph: rdflib.Graph | str
    :param args:
    :param shacl_graph:
    :param inference:
    :type inference: str | None
    :param abort_on_error:
    :param kwargs:
    :return:
    """
    target_graph = _load_into_graph(target_graph,
                                    rdf_format=kwargs.pop('target_graph_format', None))
    if shacl_graph is not None:
        shacl_graph = _load_into_graph(shacl_graph,
                                       rdf_format=kwargs.pop('shacl_graph_format', None))
    validator = Validator(
        target_graph, shacl_graph,
        options={'inference': inference, 'abort_on_error': abort_on_error})
    conforms, report_graph = validator.run()
    if kwargs.pop('check_expected_result', False):
        return check_expected_result(report_graph, shacl_graph or target_graph)
    do_serialize_report_graph = kwargs.pop('serialize_report_graph', False)
    if do_serialize_report_graph:
        if not (isinstance(do_serialize_report_graph, str)):
            do_serialize_report_graph = 'turtle'
        report_graph = report_graph.serialize(None, encoding='utf-8',
                                              format=do_serialize_report_graph)
    return conforms, report_graph


def check_expected_result(report_graph, expected_result_graph):
    DASH = rdflib.namespace.Namespace('http://datashapes.org/dash#')
    DASH_TestCase = DASH.term('GraphValidationTestCase')
    DASH_expectedResult = DASH.term('expectedResult')

    test_cases = expected_result_graph.subjects(RDF_type, DASH_TestCase)
    test_cases = set(test_cases)
    if len(test_cases) < 1:
        raise RuntimeError("Cannot check the expected result, the given expected result graph does not have a GraphValidationTestCase.")
    test_case = next(iter(test_cases))
    expected_results = expected_result_graph.objects(test_case, DASH_expectedResult)
    expected_results = set(expected_results)
    if len(expected_results) < 1:
        raise RuntimeError("Cannot check the expected result, the given GraphValidationTestCase does not have an expectedResult.")
    expected_result = next(iter(expected_results))
    expected_conforms = expected_result_graph.objects(expected_result, SH_conforms)
    expected_conforms = set(expected_conforms)
    if len(expected_conforms) < 1:
        raise RuntimeError("Cannot check the expected result, the given expectedResult does not have an sh:conforms.")
    expected_conforms = next(iter(expected_conforms))
    expected_result_nodes = expected_result_graph.objects(expected_result, SH_result)
    expected_result_nodes = set(expected_result_nodes)
    expected_result_node_count = len(expected_result_nodes)

    validation_reports = report_graph.subjects(RDF_type, SH_ValidationReport)
    validation_reports = set(validation_reports)
    if len(validation_reports) < 1:
        raise RuntimeError("Cannot check the validation report, the report graph does not contain a ValidationReport")
    validation_report = next(iter(validation_reports))
    report_conforms = report_graph.objects(validation_report, SH_conforms)
    report_conforms = set(report_conforms)
    if len(report_conforms) < 1:
        raise RuntimeError("Cannot check the validation report, the report graph does not have an sh:conforms.")
    report_conforms = next(iter(report_conforms))

    if bool(expected_conforms.value) != bool(report_conforms.value):
        log.error("Expected Result Conforms value is different from Validation Report's Conforms value.")
        return False
    report_result_nodes = report_graph.objects(validation_report, SH_result)
    report_result_nodes = set(report_result_nodes)
    report_result_node_count = len(report_result_nodes)

    if expected_result_node_count != report_result_node_count:
        log.error("Number of expected result's sh:result entries is different from Validation Report's sh:result entries.\n"
                  "Expected {}, got {}.".format(expected_result_node_count, report_result_node_count))
        return False
    # Note it is not easily achievable with this method to compare actual result entries, because they are all blank nodes.
    return True





