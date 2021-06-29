# Turbonomic Namespace Utilization Report

This integration generates a utilization report for the Kubernetes/Openshift namespaces
managed by Turbonomic.  The report is based on the data from the previous full month and allows some
customization depending on your needs.  It is designed to run as a cronjob within a Kubernetes/Openshift
environment using the turbointegrations namespace and will ultimately emails the report to specified email addresses.

## Installation

This solution uses a custom image that is available from Docker Hub.  You will also need to create a kubernetes secret, configmap and
cronjob to deploy into Kubernetes.

### Kubernetes Secret

A Kubernetes secret is used to store the credentials for the Turbonomic instance as well as the SMTP server if required.
To create the secret, execute the following commands:

```bash
$ kubectl create secret generic namespace-util-secret -n turbointegrations \
--from-literal=TURBO_USER=<turbousername> --from-literal=TURBO_PASS=<turbopassword>

$ kubectl label secret namespace-util-secret -n turbointegrations \
environment=prod \
team=turbointegrations \
app=namespace-util-report
```

Replacing the \<turbousername\> and \<turbopassword\> values with a Turbonomic username and password for your instance.  The account
needs Observer role or greater. 
If you need to authenticate to your SMTP server, you should also use the following commands:

```bash
$ kubectl create secret generic namespace-util-secret -n turbointegrations \
--from-literal=TURBO_USER=<turbousername> --from-literal=TURBO_PASS=<turbopassword>
--from-literal=NS_USERNAME=<smtpusername> --from-literal=NS_PASSWORD=<smtppassword>
```

You should also assign labels to the secret.  Feel free to customize them based on your environment:

```bash
$ kubectl label secret namespace-util-secret -n turbointegrations \
environment=prod \
team=turbointegrations \
app=namespace-util-report
```

Again replacing the \<turbousername\> and \<turbopassword\> values with a Turbonomic username and password for your instance but also replacing
\<smtpusername\> and \<smtppassword\> with the username and password for the SMTP server.

### Configmap Configuration

The configmap contains settings that are customizable depending on the particular use case for the report.  The following are the available settings
supported:

* `TURBO_HOST`
  * The Turbonomic host to query namespaces data from
  * Required
* `NS_SMTP_SERVER`
  * An external SMTP server to use to send email
  * Required
* `NS_SMTP_PORT: '25'`
  * Port to use for the SMTP server
  * Optional (Default: 25)
* `NS_FROM_ADDRS`
  * The email address of the sender
  * Required
* `NS_TO_ADDRS`
  * A list of email addresses separated by a colon ':' to send the namespace report to
  * Required
* `TAGS`
  * Tags to include in the report separated by a colon ':'
  * Each tag will provide a column in the report for each namespace with the value
  * Optional (Default: None)
* `NS_TLS`
  * Whether or not TLS is required for the SMTP server
  * Optional (Default: False)
* `NS_AUTH`
  * Whether or not the SMTP requires authentication
  * Optional (Default: False)
* `NS_BODY`
  * An optional body to the email
  * Optional (Default: None)
* `EXCLUDED_NAMES`
  * Prefix of namespaces to exclude from the report separated by a colon ':'
  * Optional (Default: default:kube:openshift)
* `EXCLUDE_MASTER`
  * Turbonomic groups of nodes (master and infrastructure nodes) to exclude from calculating namespace capacity separated by a colon ':'
  * Optional (Default: NodeRole-master:NodeRole-infra)
* `COMMODITIES`
  * Commodities to include in the report separated by a colon ':'
  * Valid options: VCPU, VCPURequestQuota, VCPULimitQuota, VMem:VMemRequestQuota, VMemLimitQuota
  * Optional (Default: VCPU:VCPURequestQuota:VCPULimitQuota:VMem:VMemRequestQuota:VMemLimitQuota)
* `METRICS`
  * Commodities to include in the report separated by a colon ':'
  * Valid options: average, peak, capacity, sum
  * Optional (Default: average:peak:capacity:sum)
* `NS_FILETYPE`
  * Filetype of the report
  * Valid options: csv, xlsx
  * Optional (Default: csv)
* `NS_FILENAME`
  * Name of the report file (current date will automatically be appended to the filename)
  * Optional (Default: namespaceReport_)
* `LOGLEVEL`
  * Level of logging messages
  * Valid options: INFO, DEBUG
  * Optional (Default: Info)

You can find a example of the configmap as a file within the repo as well as listed below:

#### Example namespace-configmap.yaml

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: namespace-util-cm
  namespace: turbointegrations
  labels:
    environment: prod
    team: turbointegrations
    app: namespace-util
    version: 0.0.4
data:
  TURBO_HOST: ''
  NS_SMTP_SERVER: ''
  NS_SMTP_PORT: '25'
  NS_FROM_ADDRS: ''
  NS_TO_ADDRS: ''
  NS_SUBJECT: 'Namespace Util Report'
  #TAGS: ''
  #NS_TLS: ''
  #NS_AUTH: ''
  #NS_BODY: ''
  #EXCLUDED_NAMES: 'default:kube:openshift'
  #EXCLUDE_MASTER: 'NodeRole-master:NodeRole-infra'
  #COMMODITIES: 'VCPU:VCPURequestQuota:VCPULimitQuota:VMem:VMemRequestQuota:VMemLimitQuota'
  #METRICS: 'average:peak:capacity:sum'
  #NS_FILETYPE: 'csv'
  #NS_FILENAME: 'namespaceReport_'
  #LOGLEVEL: ''
```

You may also wish to modify the labels within the configmap to match your environment.  Once you have configured the configmap to your requirements, apply it using the following:

```bash
$ kubectl apply -f namespace-configmap.yaml -n turbointegrations
```

### Cronjob
Now that you have the secret and configmap, you are ready to deploy the cronjob.  There is a example file within the repo as well as listed below:

#### Example namespace-cron.yaml

```yaml
apiVersion: batch/v1beta1
kind: CronJob
metadata:
  name: namespace-util
  namespace: turbointegrations
spec:
  schedule: "0 1 1 * *"
  concurrencyPolicy: Forbid
  suspend: false
  jobTemplate:
    metadata:
      generateName: namespace-util
      labels:
        environment: prod
        team: turbointegrations
        app: namespace-util
        version: 0.0.4
    spec:
      backoffLimit: 0
      template:
        metadata:
          labels:
            environment: prod
            team: turbointegrations
            app: namespace-util
            version: 0.0.4
        spec:
          securityContext:
            runAsUser: 1000
            runAsGroup: 1000
          containers:
            - image: namespace-util:0.0.4
              imagePullPolicy: IfNotPresent
              name: namespace-util
              envFrom:
                - configMapRef:
                    name: namespace-util-cm
                - secretRef: 
                    name: namespace-util-secret
          restartPolicy: Never
```

You will need to modify the schedule to a time of your choosing based on the [FreeBSD](https://www.freebsd.org/cgi/man.cgi?crontab%285%29) implementation of crontab.  The above
is set to run at 1am on the first of every month.  If you wish, you can also change the labels for the cronjob to match your environment.

Once you finish editing the cronjob yaml and save the file, you apply it using the following:

```
$ kubectl apply -f namespace-cron.yaml
```

This will deploy the cronjob to your Kubernetes environment on the defined scheduled.
