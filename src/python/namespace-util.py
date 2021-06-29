#!/usr/bin/env python3
import sys
import datetime
import csv
import os
import json
import logging
from urllib3 import disable_warnings, exceptions
import openpyxl
import umsg
import vmtconnect as vc
from sendmail import sendmail

# Disable SSL/TLS warnings for API calls
disable_warnings(exceptions.InsecureRequestWarning)

# Configure Logging
LOGLEVEL = os.getenv('LOGLEVEL', 'INFO').upper()
umsg.init(msg_format='%(asctime)s - %(levelname)s:  %(message)s',
        msg_prefix_format='{prefix} - ',
        level=LOGLEVEL)

umsg.add_handler(logging.StreamHandler())


class NamespaceTopology():
    """Class to represent all of the Namespaces in a Topology

    """
    def __init__(self, conn, commodities=None, metrics=None, tags=None, **kwargs):
        self._conn = conn
        self.commodities = commodities if commodities else ['VCPU', 'VCPURequestQuota', 'VCPULimitQuota', 'VMem', 'VMemRequestQuota', 'VMemLimitQuota']
        self.metrics = [x.lower() for x in (metrics if metrics else ['average', 'peak', 'capacity', 'sum'])]
        self._startDate,self._endDate = NamespaceTopology.get_start_end_last_month()

        if 'excluded_namespaces'in kwargs:
            if kwargs['excluded_namespaces']:
                self._exclude_namespaces = kwargs['excluded_namespaces']
            else:
                self._exclude_namespaces = []
        else:
            self._exclude_namespaces = ['default', 'kube', 'openshift']
        
        self._namespaces = self._get_namespaces()
        self._exclude_master = kwargs['exclude_master'] if 'exclude_master'in kwargs else ['NodeRole-master', 'NodeRole-infra']
        self.tags = tags
        self._container_clusters = ClusterTopology(self._conn, self._exclude_master)
        self._output = []
        self._headers = []

        # Log configuration that will be used
        umsg.log(f"Reporting using the following commodities: {self.commodities}", level=logging.INFO)
        umsg.log(f"Reporting using the following metrics: {self.metrics}", level=logging.INFO)
        umsg.log(f"Excluding the following namespace(s): {self._exclude_namespaces}", level=logging.INFO)
        umsg.log(f"Excluding Nodes from the following group(s) defined in Turbonomic: {self._exclude_master}", level=logging.INFO)
        umsg.log(f"Including the following tag(s) in the report: {self.tags}", level=logging.INFO)


    def _get_namespaces(self):
        """Get all namespaces to include in topology except for those excluded via self._exclude_namespaces"""
        search = self._conn.search(types=['Namespace'], pager=True)
        selected_Namespaces = {}

        while not search.complete:
                search_paged = search.next

                for namespace in search_paged:
                    if not any(substring in namespace['displayName'] for substring in self._exclude_namespaces):
                        selected_Namespaces.update({namespace['uuid']:NamepaceEntity(self._conn, namespace, self._startDate, self._endDate, self.commodities)})

                del search_paged
        return selected_Namespaces
    
    @staticmethod
    def get_start_end_last_month():
        """Static method to determine the previous months first and last day"""

        last_daymonth = (datetime.date.today().replace(day=1) - datetime.timedelta(days=1))
        first_daymonth = last_daymonth.replace(day=1)
        umsg.log(f'Pulling data between {first_daymonth.strftime("%Y-%m-%dT%H:%M:%SZ")} and {last_daymonth.strftime("%Y-%m-%dT%H:%M:%SZ")}', level=logging.INFO)
        return [first_daymonth.strftime("%Y-%m-%dT%H:%M:%SZ"),last_daymonth.strftime("%Y-%m-%dT%H:%M:%SZ")]

    def _create_output(self):
        """Method to create the list used populate the self._output attribute with data for output"""
        # Interate through the namespaces
        for each in self._namespaces.values():
            # Get the number of cores and total speed for the namespace
            cluster_cores = self._container_clusters.clusters[each.cluster_uuid].numCores
            cluster_mhz = self._container_clusters.clusters[each.cluster_uuid].total_mhz
            
            # Store current namespace name and cluster in temporary list variable
            namespace_data = [each.name, each.cluster]

            # Add tag data if requested
            if self.tags:
                namespace_data.extend(self._add_tag_data(each.tags))
            
            namespace_data.extend(self._add_stats_to_ouput(each))
            self._output.append(namespace_data)

        return True

    def _add_tag_data(self, ns_tags):
        # Add tag data if requested
        tag_output = []
        for tag in self.tags:

            try:
                tag_output.extend(ns_tags.get(tag))
            except TypeError:
                tag_output.append(None)
                continue
        return tag_output

    def _add_stats_to_ouputDEPRECATED(self, namespace):
        
        # Temporary list variable to store stats data
        namespace_stats =[]
        
        # Get the number of cores and total speed for the namespace to calculate millicores
        cluster_cores = self._container_clusters.clusters[namespace.cluster_uuid].numCores
        cluster_mhz = self._container_clusters.clusters[namespace.cluster_uuid].total_mhz
        
        # Iterate through requested commodities/metrics and store stats
        try:
            for commodity in self.commodities:
                
                stat_average = namespace.stats[commodity]['sum']/namespace.stats[commodity]['count']
                stat_capacity = None if namespace.stats[commodity]['capacity'] == 1000000000000.0 else namespace.stats[commodity]['capacity']
                if 'vcpu' in commodity.lower():

                    namespace_stats.extend([stat_average,
                                            self.convert_to_millicores(stat_average, cluster_cores, cluster_mhz),
                                            namespace.stats[commodity]['peak'],
                                            self.convert_to_millicores(namespace.stats[commodity]['peak'], cluster_cores, cluster_mhz), 
                                            stat_capacity,
                                            self.convert_to_millicores(stat_capacity, cluster_cores, cluster_mhz),
                                            namespace.stats[commodity]['sum'],
                                            self.convert_to_millicores(namespace.stats[commodity]['sum'], cluster_cores, cluster_mhz)])
                else:
                    namespace_stats.extend([stat_average,
                                            namespace.stats[commodity]['peak'], 
                                            stat_capacity,
                                            namespace.stats[commodity]['sum']])
        except KeyError:
            umsg.log(error_handling(), level=logging.ERROR)
            umsg.log(f"No data for Namespace {namespace.name} in the {namespace.cluster} Cluster", level=logging.ERROR)
            
        return namespace_stats

    def _add_stats_to_ouput(self, namespace):
        
        # Temporary list variable to store stats data
        namespace_stats =[]
        
        # Get the number of cores and total speed for the namespace to calculate millicores
        cluster_cores = self._container_clusters.clusters[namespace.cluster_uuid].numCores
        cluster_mhz = self._container_clusters.clusters[namespace.cluster_uuid].total_mhz
        
        # Iterate through requested commodities/metrics and store stats
        try:
            for commodity in self.commodities:
                for metric in self.metrics:
                    if metric == 'average':
                        stat_average = namespace.stats[commodity]['sum']/namespace.stats[commodity]['count']
                        namespace_stats.append(stat_average)
                        if 'vcpu' in commodity.lower():
                            namespace_stats.append(self.convert_to_millicores(stat_average, cluster_cores, cluster_mhz))

                    elif metric == 'capacity':
                        stat_capacity = None if namespace.stats[commodity]['capacity'] == 1000000000000.0 else namespace.stats[commodity]['capacity']
                        namespace_stats.append(stat_capacity)
                        if 'vcpu' in commodity.lower():
                            namespace_stats.append(self.convert_to_millicores(stat_capacity, cluster_cores, cluster_mhz))
                    else:
                        namespace_stats.append(namespace.stats[commodity][metric])
                        if 'vcpu' in commodity.lower():
                            namespace_stats.append(self.convert_to_millicores(namespace.stats[commodity][metric], cluster_cores, cluster_mhz))
        except KeyError:
            umsg.log(error_handling(), level=logging.ERROR)
            umsg.log(f"No data for Namespace {namespace.name} in the {namespace.cluster} Cluster", level=logging.ERROR)

        return namespace_stats

    def convert_to_millicores(self, value, numcores, capacity):
        """Method to convert MHz to Millicores"""
        try:
            return (value/capacity) * (numcores * 1000)
        except (TypeError, ZeroDivisionError):
            umsg.log(error_handling(), level=logging.DEBUG)
            umsg.log(f"Cannot determine millicores with a value of {value} and capacity of {capacity}", level=logging.DEBUG)
            return None

    def _create_headersOLD(self):
        """Method to create header list for CSV output of requested commodities/metrics"""
        self._headers = ['Namespace', 'Cluster']
        if self.tags:
            for tag in self.tags:
                self._headers.append(tag)
        
        for metric in self.commodities:
            if 'vcpu' in metric.lower():
                self._headers.extend([f"{metric} Average (Mhz)",
                                     f"{metric} Average (Millicores)", 
                                     f"{metric} Peak (Mhz)",
                                     f"{metric} Peak (Millicores)",
                                     f"{metric} Capacity (Mhz)",
                                     f"{metric} Capacity (Millicores)",
                                     f"{metric} Monthly Sum (Mhz)",
                                     f"{metric} Monthly Sum (Millicores)"])
            else:
                self._headers.extend([f"{metric} Average (KB)", 
                                     f"{metric} Peak (KB)",
                                     f"{metric} Capacity (KB)",
                                     f"{metric} Monthly Sum (KB)"])
        return True

    def _create_headers(self):
        """Method to create header list for CSV output of requested commodities/metrics"""
        self._headers = ['Namespace', 'Cluster']
        if self.tags:
            for tag in self.tags:
                self._headers.append(tag)
        
        for commodity in self.commodities:
            for metric in self.metrics:

                if 'vcpu' in commodity.lower():
                    self._headers.append(f"{commodity} {metric.title()} (Mhz)")
                    self._headers.append(f"{commodity} {metric.title()} (Millicores)")

                else:
                    self._headers.append(f"{commodity} {metric.title()} (KB)")

        return True


    def output_to_csv(self, filename):
        """Method to output data to CSV"""
        self._create_headers()
        self._create_output()
        
        umsg.log(f"Saving file {filename}", level=logging.INFO)
        with open(filename, 'w', newline='') as output_file:
            write_out = csv.writer(output_file)
            write_out.writerow(self._headers)
            write_out.writerows(self._output)

    def output_to_xlsx(self, filename):
        workbook = openpyxl.Workbook(write_only=True)

        ns_data = workbook.create_sheet(title=filename.split('.')[0])
        ns_data.append(self._headers)
        for row in self._output:
            ns_data.append(row)
        umsg.log(f"Saving file {filename}", level=logging.INFO)
        workbook.save(filename)


class NamepaceEntity():

    def __init__(self, conn, namespace, startDate, endDate, commodities):
        self._conn = conn
        self._uuid = namespace['uuid']
        self.name = namespace['displayName']
        self.tags = namespace.get('tags', {})
        self.cluster_uuid, self.cluster = self._get_cluster_uuid(namespace)
        self._startDate = startDate
        self._endDate = endDate
        self._namespace_stats_dto = self._set_stats_dto(commodities)
        self.stats = self._get_stats()

    def _get_cluster_uuid(self, namespace):
        for provider in namespace['providers']:
            if provider['className'] == 'ContainerPlatformCluster':
                return [provider['uuid'], provider['displayName']]
        return [None, None]
    
    def _set_stats_dto(self, commodities):
        stats_dto = {"statistics":[],
            "startDate":self._startDate,"endDate":self._endDate}

        for metric in commodities:
            stats_dto['statistics'].append({'name':metric,'relatedEntityType':'Namespace'})
        
        return stats_dto

    def _get_stats(self):
        search = self._conn.request(path=f'stats/{self._uuid}?ascending=false', method='POST', query={'ascending': False}, dto=json.dumps(self._namespace_stats_dto), pager=True)
        
        # print(f'stats/{self._uuid}')
        # print(json.dumps(self._namespace_stats_dto))
        stats = {}

        while not search.complete:

            search_paged = search.next
            # if self.name == 'irf3':
            #     print(json.dumps(search_paged))
            for date_stats in search_paged:
                if date_stats['epoch'] == 'HISTORICAL':

                    for metric in date_stats['statistics']:

                        try:
                            stats.update({metric['name']:{'count': stats[metric['name']]['count']+1, 
                                                            'sum': metric['values']['avg']+stats[metric['name']]['sum'],
                                                            'peak': max(metric['values']['max'],stats[metric['name']]['peak']),
                                                            'capacity': metric['capacity']['total']}})
                        except KeyError:
                            stats.update({metric['name']:{'count': 1, 
                                                            'sum': metric['values']['avg'], 
                                                            'peak': metric['values']['max'],
                                                            'capacity':metric['capacity']['total']}})
                            continue
                        except Exception as e:
                            umsg.log(error_handling(), level=logging.ERROR)
                            umsg.log(f"Cannot save data for {self.name} in {self.cluster}", level=logging.ERROR)
                            continue
                        
            del search_paged
        # print(self.name, self.cluster, stats)
        return stats


class ClusterTopology():

    def __init__(self, conn, exclude_master):
        self._conn = conn

        if exclude_master:
            # self._exclude_master = set(exclude_master.split(':'))
            self._master_nodes = self._get_master_Nodes(exclude_master)
        else:
            self._exclude_master = {}
        
        self.clusters = self._get_k8s_clusters()

    def _get_master_Nodes(self, exclude_master):
        master_nodes = []

        for node_group in exclude_master:
            search_dto = {"criteriaList":
                            [{"expType":"RXEQ",
                              "expVal":f"{node_group}.*",
                              "filterType":"groupsByName",
                              "caseSensitive":False}],
                            "logicalOperator":"AND",
                            "className":"Group",
                            "scope":None}
            search = self._conn.search(dto=json.dumps(search_dto), pager=True)

            while not search.complete:

                search_paged = search.next
                for group in search_paged:

                    master_nodes.extend(group['memberUuidList'])

                del search_paged
        umsg.log(f"Master Nodes: {master_nodes}", level=logging.INFO)
        return master_nodes

    def _get_k8s_clusters(self):
        clusters = {}
        search_dto = {"criteriaList":[],
                      "logicalOperator":"AND",
                      "className":"ContainerPlatformCluster",
                      "scope":None}

        search = self._conn.search(dto=json.dumps(search_dto), pager=True)

        while not search.complete:

            search_paged = search.next
            for cluster in search_paged:
                
                clusters.update({cluster['uuid']: ClusterNodes(self._conn, cluster, self._master_nodes)})

            del search_paged
        return clusters


class ClusterNodes():
    
    def __init__(self, conn, cluster, master_nodes):
        self._conn = conn
        self._uuid = cluster['uuid']
        self.name = cluster['displayName']
        self._master_nodes = master_nodes
        self.numCores, self.total_mhz = self._get_nodes_info()
        
    def _get_nodes_info(self):
        total_cores = 0
        worker_nodes = []
        search = self._conn.get_supplychains(uuids=self._uuid, 
                                              types=['VirtualMachine'], 
                                              detail='aspects',
                                              aspects=['virtualMachineAspect'],
                                              health=True, 
                                              pager=True)
        while not search.complete:

            search_paged = search.next

            for node in search_paged[0]['seMap']['VirtualMachine']['instances'].values():
                if node['state'] == 'ACTIVE' and node['uuid'] not in self._master_nodes:
                    total_cores += node['aspects']['virtualMachineAspect']['numVCPUs']
                    worker_nodes.append(node['uuid'])

            del search_paged

        total_mhz = self._get_cpu_info(worker_nodes)

        return (total_cores, total_mhz)

    def _get_cpu_info(self, worker_nodes):
        cpu_speed = 0
                
        search_dto = {'scopes':[self._uuid],'period':{'statistics':[{'name':'VCPU'}]},'relatedType':'VirtualMachine'}
        

        search = self._conn.request(path='stats', method='POST', dto=json.dumps(search_dto), pager=True)


        while not search.complete:

            search_paged = search.next
            
            for node in search_paged:
                if node['uuid'] in worker_nodes:
                    
                    for stat in node['stats'][0]['statistics']:
                        if stat['name'] == 'VCPU':
                            cpu_speed += stat['capacity']['total']

            del search_paged
        return cpu_speed


def error_handling():
    return 'Error: {}. {}, line: {}'.format(sys.exc_info()[0],
                                            sys.exc_info()[1],
                                            sys.exc_info()[2].tb_lineno)           



def main():

    ## Variables set from environment
    TURBO_HOST = os.getenv('TURBO_HOST',)
    TURBO_USER = os.getenv('TURBO_USER')
    TURBO_PASS = os.getenv('TURBO_PASS')
    COMMODITIES = os.getenv('COMMODITIES')
    TAGS = os.getenv('TAGS')
    METRICS = os.getenv('METRICS')

    # Get Env Variable for Commodities to Include 
    commodities = list(COMMODITIES.split(':')) if COMMODITIES else None
    # Get Env Variable for Tags to Include 
    tags = list(TAGS.split(':')) if TAGS else None
    # Get Env Variable for Metrics to Include
    metrics = list(METRICS.split(':')) if METRICS else None

    # Create Dictionary to pass additional kwargs
    additional_params = {}


    # Get Env Variable for Namespaces to Exclude
    if os.getenv('EXCLUDED_NAMES'):
        EXCLUDED_NAMES = os.getenv('EXCLUDED_NAMES')
    
    if 'EXCLUDED_NAMES' in locals():
        if EXCLUDED_NAMES: 
            excluded_namespaces = list(EXCLUDED_NAMES.split(':'))
        else: 
            excluded_namespaces = None
        additional_params.update({'excluded_namespaces': excluded_namespaces})
    

    # Get Env Variable for Master Node Group of Nodes to Exclude
    EXCLUDE_MASTER = os.getenv('EXCLUDE_MASTER')

    if EXCLUDE_MASTER:
        exclude_master = list(EXCLUDE_MASTER.split(':'))
        additional_params.update({'exclude_master': exclude_master})
    



    # Create Connection object to Turbonomic
    vmt = vc.Connection(host=TURBO_HOST,username=TURBO_USER, password=TURBO_PASS)
    
    # Create NamespaceTopology Object
    ns_Top = NamespaceTopology(vmt, commodities=commodities, metrics=metrics, tags=tags, **additional_params)   

    # Output NamespaceTopology to CSV
    NS_FILETYPE = os.getenv('NS_FILETYPE','csv')
    # NS_FILENAME = os.getenv('NS_FILENAME',f"namespaceReport.{NS_FILETYPE.lower()}")
    NS_FILENAME = os.getenv(f'NS_FILENAME_{datetime.datetime.strftime(datetime.datetime.now(), "%Y-%m-%d")}.{NS_FILETYPE.lower()}',
        f'namespaceReport_{datetime.datetime.strftime(datetime.datetime.now(), "%Y-%m-%d")}.{NS_FILETYPE.lower()}')

    ns_filepath = '/tmp/'
    ns_file_output = os.path.join(ns_filepath, NS_FILENAME)
    

    try:
        if NS_FILENAME.lower() == 'xlsx':
            ns_Top.output_to_xlsx(ns_file_output)
        else:
            ns_Top.output_to_csv(ns_file_output)
    except OSError:
        umsg.log(error_handling(), level=logging.ERROR)
        umsg.log(f"Cannot save to file {ns_file_output}", level=logging.ERROR)

    NS_SMTP_SERVER = os.getenv('NS_SMTP_SERVER')
    NS_SMTP_PORT = os.getenv('NS_SMTP_PORT')
    NS_FROM_ADDRS = os.getenv('NS_FROM_ADDRS')
    NS_TO_ADDRS = os.getenv('NS_TO_ADDRS')
    NS_TLS = os.getenv("NS_TLS", 'False').lower() in ('true', '1', 't')
    NS_AUTH = os.getenv("NS_AUTH", 'False').lower() in ('true', '1', 't')
    NS_USERNAME = os.getenv('NS_USERNAME')
    NS_PASSWORD = os.getenv('NS_PASSWORD')
    NS_SUBJECT = os.getenv('NS_SUBJECT')
    NS_BODY = os.getenv('NS_BODY')

    if NS_SMTP_PORT:
        smtp_port = int(NS_SMTP_PORT)
    else:
        smtp_port = 25

    if NS_TLS:
        tls = NS_TLS
    else:
        tls = False

    to_addrs = list(NS_TO_ADDRS.split(':'))
    
    sendemail = sendmail(subject=NS_SUBJECT, from_addr=NS_FROM_ADDRS, to_addr=to_addrs, smtp_addr=NS_SMTP_SERVER, smtp_port=smtp_port,tls=tls)

    if NS_BODY:
        sendemail.add_body(NS_BODY)

    if NS_AUTH:
        sendemail.add_auth(username=NS_USERNAME, password=NS_PASSWORD)

    sendemail.add_attachments([ns_file_output])
    umsg.log(f'Emailing file {ns_file_output} to {to_addrs}')
    sendemail.sendmail()
    

if __name__ == '__main__':
    main()
