import csv
import json
import zipfile
from pprint import pformat
from cStringIO import StringIO

from crowdflower import logger
from crowdflower.cache import cacheable, keyfunc
from crowdflower.serialization import rails_params


class Job(object):
    '''
    Read / Write attributes
        auto_order
        auto_order_threshold
        auto_order_timeout
        cml
        cml_fields
        confidence_fields
        css
        custom_key
        excluded_countries
        gold_per_assignment
        included_countries
        instructions
        js
        judgments_per_unit
        language
        max_judgments_per_unit
        max_judgments_per_contributor
        min_unit_confidence
        options
        pages_per_assignment
        problem
        send_judgments_webhook
        state
        title
        units_per_assignment
        webhook_uri

    Read-only attributes
        completed
        completed_at
        created_at
        gold
        golds_count
        id
        judgments_count
        units_count
        updated_at

    Not sure about:
        payment_cents

    '''
    READ_WRITE_FIELDS = ['auto_order', 'auto_order_threshold', 'auto_order_timeout', 'cml', 'cml_fields', 'confidence_fields', 'css', 'custom_key', 'excluded_countries', 'gold_per_assignment', 'included_countries', 'instructions', 'js', 'judgments_per_unit', 'language', 'max_judgments_per_unit', 'max_judgments_per_contributor', 'min_unit_confidence', 'options', 'pages_per_assignment', 'problem', 'send_judgments_webhook', 'state', 'title', 'units_per_assignment', 'webhook_uri']
    _cache_key_attrs = ('id',)

    def __init__(self, job_id, connection):
        self.id = job_id
        self._connection = connection
        self._cache = self._connection._cache

    def __repr__(self):
        return pformat(self.properties)

    @property
    @cacheable()
    def properties(self):
        return self._connection.request('/jobs/%s' % self.id)


    @cacheable('tags')
    def get_tags(self):
        res = self._connection.request('/jobs/%s/tags' % self.id)
        return [item['name'] for item in res]

    def set_tags(self, tags):
        params = rails_params({'tags': tags})
        self._connection.request('/jobs/%s/tags' % self.id, method='PUT', params=params)
        self._cache.remove(keyfunc(self, 'tags'))

    tags = property(get_tags, set_tags)

    def add_tags(self, tags):
        params = rails_params({'tags': tags})
        self._connection.request('/jobs/%s/tags' % self.id, method='POST', params=params)
        self._cache.remove(keyfunc(self, 'tags'))

    @property
    @cacheable()
    def units(self):
        '''
        Returns a dict of {unit_id: dict_of_unit_properties}, e.g.,

            {
                u'495781935': {
                    u'id': u'may25_1029',
                    u'text': u'remember when I was in hospital for four months nd it was my birthday nd everyone forgot nd no one even came to visit me'
                },
                u'495781936': {
                    u'id': u'may25_1030',
                    u'text': u'I had the wifi taken away and I can't have any friends over what a great Summer!'
                }
                ...
            }

        Automatically cached.
        '''
        self._connection.request('/jobs/%s/units' % self.id)

    def delete_unit(self, unit_id):
        response = self._connection.request('/jobs/%s/units/%s' % (self.id, unit_id), method='DELETE')
        # bust cache if the request did not raise any errors
        self._cache.remove(keyfunc(self, 'units'))
        return response

    def upload(self, units):
        headers = {'Content-Type': 'application/json'}
        data = '\n'.join(json.dumps(unit) for unit in units)
        res = self._connection.request('/jobs/%s/upload' % self.id, method='POST', headers=headers, data=data)

        # reset cached units
        self._cache.remove(keyfunc(self, 'units'))

        return res

    def update(self, props):
        params = rails_params({'job': props})
        logger.debug('Updating Job[%d]: %r', self.id, params)
        res = self._connection.request('/jobs/%s' % self.id, method='PUT', params=params)

        # reset cached properties
        self._cache.remove(keyfunc(self, 'properties'))

        return res

    def channels(self):
        '''
        Manual channel control is deprecated.

        The API documentation includes a PUT call at this endpoint, but I'm
        not sure if it actually does anything.
        '''
        return self._connection.request('/jobs/%s/channels' % self.id)

    def legend(self):
        '''
        From the CrowdFlower documentation:

        > The legend will show you the generated keys that will end up being
        > submitted with your form.
        '''
        return self._connection.request('/jobs/%s/legend' % self.id)

    def gold_reset(self):
        '''
        Mark all of this job's test questions (gold data) as NOT gold.

        Splitting the /jobs/:job_id/gold API call into gold_reset() and
        gold_add() is not faithful to the API, but resetting gold marks
        and adding them should not have the same API endpoint in the first place.
        '''
        params = dict(reset='true')
        res = self._connection.request('/jobs/%s/gold' % self.id, method='PUT', params=params)
        # reset cache
        self._cache.remove(keyfunc(self, 'properties'))
        self._cache.remove(keyfunc(self, 'units'))
        return res

    def gold_add(self, check, check_with=None):
        '''
        Configure the gold labels for a task.

        * check: the name of the field being checked against
            - Can call /jobs/{job_id}/legend to see options
            - And as far as I can tell, the job.properties['gold'] field is a
              hash with keys that are "check" names, and values that are "with" names.
        * check_with: the name of the field containing the gold label for check
            - Crowdflower calls this field "with", which is a Python keyword
            - defaults to check + '_gold'

        I'm not sure why convert_units would be anything but true.
        '''
        params = dict(check=check, convert_units='true')
        if check_with is not None:
            params['with'] = check_with
        res = self._connection.request('/jobs/%s/gold' % self.id, method='PUT', params=params)
        # reset cache
        self._cache.remove(keyfunc(self, 'properties'))
        self._cache.remove(keyfunc(self, 'units'))
        return res

    def delete(self):
        '''
        Deletes the entire job permanently
        '''
        return self._connection.request('/jobs/%s' % self.id, method='DELETE')

    def download(self, full=True):
        '''The resulting CSV will have headers like:

            _unit_id
                Integer
                Unique ID per unit
            _created_at
                Date: m/d/yyyy hh:mm:ss
            _golden
                Enum: "true" | "false"
            _canary
                Always empty, ???
            _id
                Integer
                Unique ID per judgment
            _missed
                ???
            _started_at
                Date: m/d/yyyy hh:mm:ss
                Can use
            _tainted
                Always false, ???
            _channel
                Enum: "neodev" | "clixsense" | [etc.]
            _trust
                Always 1, ???
            _worker_id
                Integer
                Unique ID per worker
            _country
                3-letter ISO code
            _region
                String
                A number for all countries except UK, USA, Canada (others?)
            _city
                String
                City name
            _ip
                String
                IPv4 address

        And then the rest just copies over whatever fields were originally used, e.g.:

            id
            text
            sentiment
            sentiment_gold
        '''
        # pulls down the csv endpoint, unzips it, and returns a list of all the rows
        params = dict(full='true' if full else 'false')
        # use .csv, not headers=dict(Accept='text/csv'), which Crowdflower rejects
        req = self._connection.create_request('/jobs/%s.csv' % self.id, method='GET', params=params)
        res = self._connection.send_request(req)
        # because ZipFile insists on seeking, we can't simply pass over the res.raw stream
        fp = StringIO()
        fp.write(res.content)
        # ZipFile does fp.seek(0) itself
        zf = zipfile.ZipFile(fp)
        for zipinfo in zf.filelist:
            zipinfo_fp = zf.open(zipinfo)
            reader = csv.DictReader(zipinfo_fp)
            for row in reader:
                yield {key: value.decode('utf8') for key, value in row.items()}

    @property
    @cacheable()
    def judgments(self):
        return self.download()
