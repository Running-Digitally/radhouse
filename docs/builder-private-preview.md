# Builder private preview

Builder's first V1 workflow is intentionally one fixed private preview slot:

```text
assignment in Buzz
  -> Builder edits one project workspace
  -> Docker Compose builds and starts one application on the Builder VM
  -> the Operations VM proxies one fixed HTTPS hostname to that application
  -> Builder checks the main user journey and returns the preview link in Buzz
  -> follow-up messages update the application behind the same link
```

The bot VM remains the worker boundary. The preview container is a replaceable
project environment, not a stronger isolation claim. It receives no Radhouse,
hypervisor, DNS, certificate, or infrastructure credentials. The Builder may
inspect its workspace, images, containers and application logs without operator
handoffs.

The private deployment overlay assigns the hostname and backend address. The
hostname resolves only through the installation's private DNS and reaches the
existing private-network/WARP path. One static reverse-proxy route terminates
trusted TLS outside the bot VM. The Builder publishes only the assigned backend
port, and the surrounding network admits that port only from the proxy host.

For the first slice, source and Compose configuration are durable; experiment
data is disposable unless the assignment says otherwise. Builder must run a
user-visible smoke check before reporting readiness. Updating the preview keeps
the same URL. Stopping it removes access while retaining source.

This slice does not provide dynamic VM creation, arbitrary host registration,
public ingress, autoscaling, shared production hosting, deployment scheduling,
or a generic orchestration API. Add another preview slot only after concurrent
use demonstrates the need.

## Second bot setup

Add the Builder runtime to `bots`, add a corresponding signed Buzz agent entry,
and create a separate SSH tunnel instance for its loopback Hermes endpoint. The
operator may then grant the configured bot to an existing person/project without
rotating that person's password or MFA secret:

```sh
radhouse bot-grant --config /etc/radhouse/config.yaml \
  --principal-id PERSON --project-id PROJECT --bot-id builder-01 \
  --bot-display-name Builder --bot-role-name Builder --apply
```

The command refuses an absent or inactive person/project and refuses profile
drift for an existing bot ID. Buzz advertises the configured bot role rather
than assuming every agent is a Researcher.

Acceptance is one useful small application opened through the private HTTPS
link, one meaningful follow-up deployed at the same link, restart recovery of
the source and running preview, and denial from outside the admitted LAN/WARP
path.
