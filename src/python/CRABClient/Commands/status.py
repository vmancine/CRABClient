from __future__ import division # I want floating points

from CRABClient.Commands.SubCommand import SubCommand
from CRABClient.ServerInteractions import HTTPRequests
from CRABClient.client_exceptions import MissingOptionException, RESTCommunicationException

class Resp:
    campaign, campaignStatus, jobsPerState, detailsPerState, detailsPerSite = range(5)

class status(SubCommand):
    """
    Query the status of your tasks, or detailed information of one or more tasks
    identified by -t/--task option
    """

    shortnames = ['st']

    states = ['submitted', 'failure', 'queued', 'success']
    abbreviations = {'submitted' : 's', 'failure': 'f', 'queued' : 'q', 'success' : 'u'}
    def __call__(self):
        server = HTTPRequests(self.serverurl, self.proxyfilename)

        self.logger.debug('Looking up detailed status of task %s' % self.cachedinfo['RequestName'])
        dictresult, status, reason = server.get(self.uri, data = { 'campaign' : self.cachedinfo['RequestName']})

        if status != 200:
            msg = "Problem retrieving status:\ninput:%s\noutput:%s\nreason:%s" % (str(self.cachedinfo['RequestName']), str(dictresult), str(reason))
            raise RESTCommunicationException(msg)

        #TODO: _printRequestDetails
        self.logger.debug(dictresult)
        listresult = dictresult['result']

        if self.options.site or self.options.failure:
            errresult, status, reason = server.get('/crabserver/workflow', \
                                data = { 'workflow' : self.cachedinfo['RequestName'], 'subresource' : 'errors', 'shortformat' : 1 if self.options.failure else 0})
            if status != 200:
                msg = "Problem retrieving status:\ninput:%s\noutput:%s\nreason:%s" % (str(self.cachedinfo['RequestName']), str(errresult), str(reason))
                raise RESTCommunicationException(msg)
            self.logger.debug(str(errresult))

        self.logger.info("Task Status:\t\t%s" % listresult[Resp.campaignStatus])
        states = listresult[Resp.jobsPerState]
        total = sum( states[st] for st in states )
        frmt = ''
        resubmissions = 0
        for status in states:
            if states[status] > 0 and status not in ['total', 'first', 'retry']:
                frmt += status + ' %.1f %%\t' % ( states[status]*100/total )
        if frmt == '' and total != 0:
            frmt = 'jobs are being submitted'
        self.logger.info('Details:\t\t%s' % frmt)

        self.logger.info(('Using %d site(s):\t' % len(listresult[Resp.detailsPerSite])) + \
                           ('' if len(listresult[Resp.detailsPerSite])>4 else ', '.join(listresult[Resp.detailsPerSite].keys())))

        if self.options.site:
            if not listresult[Resp.detailsPerSite]:
                self.logger.info("Information per site are not available.")
            for site in listresult[Resp.detailsPerSite]:
                self.logger.info("%s: " % site)
                states = listresult[Resp.detailsPerSite][site][0]
                frmt = '    '
                for status in states:
                    if states[status] > 0:
                        frmt += status + ' %.1f %%\t' % ( states[status]*100/total )
                self.logger.info(frmt)
                self._printSiteErrors(errresult, site, total)

        for status in self.states:
            if listresult[Resp.detailsPerState].has_key(status) and listresult[Resp.detailsPerState][status].has_key('retry'):
                resubmissions += listresult[Resp.detailsPerState][status]['retry']
            if getattr(self.options, status) and listresult[Resp.detailsPerState].has_key(status):
                states = listresult[Resp.detailsPerState][status]
                frmt = status + " breakdown:\t"
                for st in states:
                    if st != 'first' and st != 'retry':
                        frmt += st + '   %.1f %%\t' % ( states[st]*100/total )
                self.logger.info(frmt)

        if resubmissions:
            self.logger.info('%.1f %% using the automatic resubmission' % (resubmissions*100/total))

        #XXX: The exit code here is the one generated by Report.getExitCode and is not necessarily the CMSSWException one
        if self.options.failure:
            self.logger.info("List of errors:")
            for err in errresult['result'][0]:
                self.logger.info("  %.1f %% have exit code %s" % (err['value']*100/total, err['key'][2]))

    def _printSiteErrors(self, errresult, site, total):
        """
        Print the error details of the site (when option -i is used)
        """
        _, _, EXITCODE, ERRLIST, SITE = range(5)
        if errresult.has_key('result') and len(errresult['result'])>0:
            for row in errresult['result'][0]:
                if row['key'][SITE] == site:
                     self.logger.info("    %.1f %% with exit code %s. Error list: %s" % (row['value']*100/total, row['key'][EXITCODE], row['key'][ERRLIST]))

    def _printRequestDetails(self, dictresult):
        """
        Print the RequestMessages list when the task is failed
        """
        if dictresult.has_key('requestDetails') and \
                  dictresult['requestDetails'][u'RequestStatus'] == 'failed' and \
                  dictresult['requestDetails'].has_key(u'RequestMessages'):
            for messageL in dictresult['requestDetails'][u'RequestMessages']:
                #messages are lists
                for message in messageL:
                    self.logger.info("   Server Messages:")
                    self.logger.info("   \t%s" % message)


    def setOptions(self):
        """
        __setOptions__

        This allows to set specific command options
        """
        for status in self.states:
            self.parser.add_option( "-"+self.abbreviations[status], "--"+status,
                                 dest = status,
                                 action = "store_true",
                                 default = False,
                                 help = "Provide details about %s jobs" % status)

        self.parser.add_option( "-i", "--site",
                                 dest = "site",
                                 action = "store_true",
                                 default = False,
                                 help = "Provide details about sites" )



    def readableRange(self, jobArray):
        """
        Take array of job numbers and concatenate 1,2,3 to 1-3
        return string
        """
        def readableSubRange(subRange):
            """
            Return a string for each sub range
            """
            if len(subRange) == 1:
                return "%s" % (subRange[0])
            else:
                return "%s-%s" % (subRange[0], subRange[len(subRange)-1])

        # Sort the list and generate a structure like [[1], [4,5,6], [10], [12]]
        jobArray.sort()

        previous = jobArray[0]-1
        listOfRanges = []
        outputJobs = []
        for job in jobArray:
            if previous+1 == job:
                outputJobs.append(job)
            else:
                listOfRanges.append(outputJobs)
                outputJobs = [job]
            previous = job
        if outputJobs:
            listOfRanges.append(outputJobs)

        # Convert the structure to a readable string
        return ','.join([readableSubRange(x) for x in listOfRanges])
