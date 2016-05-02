from __future__ import print_function

import argparse
import getpass
import os
import subprocess
import sys

import paramiko


DEFAULT_SSH_DIR = os.path.join(os.path.expanduser("~"), '.ssh')

DEFAULT_KNOWN_HOSTS = os.path.join(DEFAULT_SSH_DIR, 'known_hosts')
DEFAULT_SSH_CONFIG = os.path.join(DEFAULT_SSH_DIR, 'config')
DEFAULT_SSH_DSA = os.path.join(DEFAULT_SSH_DIR, 'id_dsa')
DEFAULT_SSH_RSA = os.path.join(DEFAULT_SSH_DIR, 'id_rsa')
DEFAULT_SSH_PORT = 22


def main():
    mc = Main()
    mc.main()


class Main(object):

    def __init__(self):
        self.args = None
        self.priv_key = None
        self.pub_key = None
        self.pub_key_content = None

    def main(self):
        # Parse input arguments
        self.args = self.parse_args(sys.argv)

        # Check SSH key argument
        if not self.args.identity:
            self.args.identity = os.path.expanduser(DEFAULT_SSH_RSA)
            if not os.path.exists(self.args.identity):
                self.args.identity = os.path.expanduser(DEFAULT_SSH_DSA)
                if not os.path.exists(self.args.identity):
                    print('Error: Cannot find any SSH keys in {0} and {1}.'.format(DEFAULT_SSH_RSA, DEFAULT_SSH_DSA),
                          file=sys.stderr)
                    sys.exit(1)
        self.priv_key = self.args.identity
        self.pub_key = '{0}.pub'.format(self.args.identity)

        # Read the public key
        with open(self.pub_key) as fh:
            self.pub_key_content = fh.read().strip()

        # Load ~/.ssh/config if it exists
        config = load_config()

        # Parse the hosts to extract the username if given
        hosts = parse_hosts(self.args.hosts, config)  # list of Host objects

        # Check the action to perform
        if self.args.key or self.args.known_hosts:
            # Add the remote hosts' SSH keys only
            if not self.args.known_hosts:
                self.args.known_hosts = DEFAULT_KNOWN_HOSTS

            # Add the remote hosts' SSH public keys to the known_hosts
            self.add_to_known_hosts(hosts, known_hosts=self.args.known_hosts)

        else:
            # Copy the SSH keys to the hosts

            # Check that a password is given
            if not self.args.password:
                if not sys.stdin.isatty():
                    self.args.password = sys.stdin.readline().strip()
                else:
                    self.args.password = getpass.getpass('Enter the common password: ')
            for host in hosts:
                host.password = self.args.password

            self.copy_ssh_keys(hosts)

    def parse_args(self, argv):
        parser = argparse.ArgumentParser(description='Massively copy SSH keys.')
        parser.add_argument('hosts', metavar='host', nargs='+',
                            help='the remote hosts to copy the keys to.  Syntax: [user@]hostname')
        parser.add_argument('-i', '--identity', help='the SSH identity file. Default: {0} or {1}'
                                                     .format(DEFAULT_SSH_RSA, DEFAULT_SSH_DSA))
        parser.add_argument('-k', '--key', action='store_true',
                            help='don\'t copy the SSH keys, but instead, add the remote hosts SSH public keys to the '
                                 '~/.ssh/known_hosts file.')
        parser.add_argument('-K', '--known-hosts',
                            help='same as --key but with specifying the "known_hosts" file.')
        parser.add_argument('-P', '--password',
                            help='the password to log into the remote hosts.  It is NOT SECURED to set the password '
                                 'that way, since it stays in the bash history.  Password can also be sent on the '
                                 'STDIN.')
        return parser.parse_args(argv[1:])

    def add_to_known_hosts(self, hosts, known_hosts=DEFAULT_KNOWN_HOSTS):
        """
        Add the remote host SSH public key to the `known_hosts` file.

        :param hosts: the list of the remote `Host` objects.
        :param known_hosts: the `known_hosts` file to store the SSH public keys.
        """
        to_add = []
        with open(known_hosts) as fh:
            known_hosts_set = set(line.strip() for line in fh.readlines())

        cmd = ['ssh-keyscan'] + [host.hostname for host in hosts]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = p.communicate()
        for line in stdout.splitlines():
            line = line.strip()
            print('[{0}] Add the remote host SSH public key to [{1}]...'
                  .format(line.split(' ', 1)[0], known_hosts))
            if line not in known_hosts_set:
                known_hosts_set.add(line)
                to_add.append('{0}\n'.format(line))

        with open(known_hosts, 'a') as fh:
            fh.writelines(to_add)

    def copy_ssh_keys(self, hosts):
        """
        Copy the SSH keys to the `host`.

        :param hosts: the list of `Host` objects to copy the SSH keys to.
        """
        for host in hosts:
            print('[{0}] Copy the SSH public key [{1}]...'.format(host.hostname, self.pub_key))
            with paramiko.SSHClient() as client:
                client.set_missing_host_key_policy(paramiko.client.AutoAddPolicy())
                client.load_host_keys(filename=DEFAULT_KNOWN_HOSTS)
                client.connect(host.hostname, username=host.user, password=host.password, key_filename=self.priv_key)
                cmd = r'''mkdir -p ~/.ssh && chmod 700 ~/.ssh && \
k='{0}' && if ! grep -qFx "$k" ~/.ssh/authorized_keys; then echo "$k" >> ~/.ssh/authorized_keys; fi'''\
                        .format(self.pub_key_content)
                client.exec_command(cmd)


def load_config(config=DEFAULT_SSH_CONFIG):
    config_obj = paramiko.config.SSHConfig()
    if os.path.isfile(config):
        with open(config) as fh:
            config_obj.parse(fh)
    return config_obj


def parse_hosts(hosts, config):
    host_list = []  # list of Host objects
    current_user = getpass.getuser()
    for host in hosts:
        d = config.lookup(host)
        if '@' in host:
            user, hostname = host.split('@', 1)
        else:
            user = d.get('user', current_user)
            hostname = host
        host_list.append(Host(hostname=hostname, port=d.get('port', DEFAULT_SSH_PORT), user=user))

    return host_list


class Host(object):

    def __init__(self, hostname=None, port=DEFAULT_SSH_PORT, user=None, password=None):
        self.hostname = hostname
        self.port = port
        self.user = user
        self.password = password
