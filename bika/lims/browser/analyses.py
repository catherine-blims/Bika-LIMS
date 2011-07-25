from AccessControl import Unauthorized
from DateTime import DateTime
from Products.Archetypes.config import REFERENCE_CATALOG
from Products.CMFCore.WorkflowCore import WorkflowException
from Products.CMFCore.utils import getToolByName
from Products.CMFPlone.utils import transaction_note
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from bika.lims import bikaMessageFactory as _
from bika.lims.browser.bika_listing import BikaListingView
from bika.lims.browser.client import ClientAnalysisRequestsView
from bika.lims.config import POINTS_OF_CAPTURE
from decimal import Decimal
from operator import itemgetter
from plone.app.content.browser.interfaces import IFolderContentsView
from zope.component import getMultiAdapter
from zope.interface import implements,alsoProvides
import json
import plone

class AnalysesView(BikaListingView):
    """ Displays a list of Analyses in a table.
        All InterimFields from all analyses are added to self.columns[].
        allow_edit boolean decides if edit is possible, but each analysis
        can be editable or not, depending on it's review_state.
        Keyword arguments are passed directly to portal_catalog.
    """
    content_add_actions = {}
    show_filters = False
    show_sort_column = False
    show_select_row = False
    show_select_column = False
    pagesize = 1000
    columns = {
        'Service': {'title': _('Analysis')},
        'Result': {'title': _('Result'),
                   'allow_edit': True},
        'Uncertainty': {'title': _('+-')},
        'retested': {'title': _('Retested'),
                     'allow_edit': True,
                     'type':'boolean'},
        'Attachments': {'title': _('Attachments')},
    }
    review_states = [
        {'title': _('All'), 'id':'all',
         'columns':['Service',
                    'Result',
                    'Uncertainty',
                    'retested',
                    'Attachments'],
         },
    ]
    def __init__(self, context, request, allow_edit = False, **kwargs):
        super(AnalysesView, self).__init__(context, request)
        self.contentFilter = dict(kwargs)
        self.contentFilter['portal_type'] = 'Analysis'

    def folderitems(self):
        """ InterimFields are inserted into self.columns before 'Result',
            XXX not specifically ordered but vaguely predictable.
        """
        pc = getToolByName(self.context, 'portal_catalog')

        analyses = super(AnalysesView, self).folderitems(full_objects = True)

        items = []
        self.interim_fields = {}
        for i, item in enumerate(analyses):
            if not item.has_key('obj'): continue
            # self.contentsMethod may return brains or objects.
            if hasattr(item['obj'], 'getObject'):
                obj = item['obj'].getObject()
            else:
                obj = item['obj']

            # calculate specs - they are stored in an attribute on each row so that selecting
            # lab/client ranges can re-calculate in javascript
            # calculate specs for every analysis, since they may
            # all be for different sample types
            specs = {'client':{}, 'lab':{}}
            if obj.portal_type != 'ReferenceAnalysis':
                if self.context.portal_type == 'AnalysisRequest':
                    proxies = pc(portal_type = 'AnalysisSpec',
                                 getSampleTypeUID = self.context.getSample().getSampleType().UID())
                else: # worksheet.  XXX fix this, man.  It should be like a generalized review_state_filter
                    proxies = pc(portal_type = 'AnalysisSpec',
                                 getSampleTypeUID = obj.aq_parent.getSample().getSampleType().UID())
                for spec in proxies:
                    spec = spec.getObject()
                    client_or_lab = ""
                    if spec.getClientUID() == self.context.getClientUID():
                        client_or_lab = 'client'
                    elif spec.getClientUID() == None:
                        client_or_lab = 'lab'
                    else:
                        continue
                    for keyword, results_range in spec.getResultsRangeDict().items():
                        specs[client_or_lab][keyword] = results_range


            result = obj.getResult()
            service = obj.getService()
            keyword = service.getKeyword()
            choices = service.getResultOptions()

            item['specs'] = json.dumps(
                {'client': specs['client'].has_key(keyword) and specs['client'][keyword] or [],
                 'lab': specs['lab'].has_key(keyword) and specs['lab'][keyword] or [],
                 })

            obj.getInterimFields()

            item['Service'] = service.Title()
            item['Keyword'] = keyword
            item['Result'] = result
            item['Unit'] = obj.getUnit()
            item['Uncertainty'] = obj.getUncertainty(result)
            item['retested'] = obj.getRetested()
            item['allow_edit'] = self.allow_edit or False
            item['calculation'] = service.getCalculation() and True or False

            if choices:
                item['ResultOptions'] = choices

            item['item_data'] = json.dumps(item['interim_fields'])

            if hasattr(obj, 'getAttachment'):
                item['Attachments'] = ", ".join([a.Title() for a in obj.getAttachment()])
            else:
                item['Attachments'] = ''

            if hasattr(obj, 'result_in_range'):
                item['result_in_range'] = obj.result_in_range(result)
            else:
                item['result_in_range'] = True

            # Add this analysis' interim fields to the list
            for f in item['interim_fields']:
                if f['id'] not in self.interim_fields.keys():
                    self.interim_fields[f['id']] = f['title']
                item[f['id']] = f

            items.append(item)

        items = sorted(items, key=itemgetter('Service'))

        interim_keys = self.interim_fields.keys()
        interim_keys.reverse()

        # add InterimFields keys to columns
        for col_id in interim_keys:
            if col_id not in self.columns:
                self.columns[col_id] = {'title': self.interim_fields[col_id]}

        # Add InterimFields keys to review_states column lists
        munged_states = []
        for state in self.review_states:
            pos = state['columns'].index('Result')
            if not pos: pos = len(state['columns'])
            for col_id in interim_keys:
                if col_id not in state['columns']:
                    state['columns'].insert(pos, col_id)
            munged_states.append(state)
        self.review_states = munged_states

        # re-do the pretty css odd/even classes
        for i in range(len(items)):
            items[i]['table_row_class'] = ((i + 1) % 2 == 0) and "draggable even" or "draggable odd"

        return items