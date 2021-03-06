import random
import copy
import json
import random
import hashlib
import numpy as np
import networkx as nx
import matplotlib.pyplot as plt

from blocks import Block
from validator import Validator
from validator import ConsensusMessage
from validator import UnresolvedDeps
from generate_transactions import gen_alice_and_bob_tx

from config import *

# Setup
GENESIS_BLOCKS = {}
GENESIS_MESSAGES = []
for ID in SHARD_IDS:
    GENESIS_BLOCKS[ID] = Block(ID)
    GENESIS_MESSAGES.append(ConsensusMessage(GENESIS_BLOCKS[ID], 0, []))  # The watcher is the sender of the genesis blocks

validators = {}
for name in VALIDATOR_NAMES:
    validators[name] = Validator(name)

#  Watcher lives at validator name 0 and receives all the messages
watcher = validators[0]

for v in VALIDATOR_NAMES:
    for genesis_message in GENESIS_MESSAGES:
        validators[v].receive_consensus_message(genesis_message)

# GLOBAL MEMPOOLS
mempools = {}
txs = gen_alice_and_bob_tx()
for ID in SHARD_IDS:
    mempools[ID] = txs

# GLOBAL VIEWABLES
viewables = {}
for v in VALIDATOR_NAMES:
    viewables[v] = {}
    for w in VALIDATOR_NAMES:
        viewables[v][w] = []

max_height = 0

# SIMULATION LOOP:
for i in range(NUM_ROUNDS):
    # Make a new message from a random validator on a random shard
    rand_ID = random.choice(SHARD_IDS)
    next_proposer = rand.choice(SHARD_VALIDATOR_ASSIGNMENT[rand_ID])

    if next_proposer == 0:
        i -= 1  # skip but don't waste the round!
        continue

    # MAKE CONSENSUS MESSAGE
    new_message = validators[next_proposer].make_new_consensus_message(rand_ID, mempools, drain_amount=MEMPOOL_DRAIN_RATE)

    # keep max_height
    if new_message.height > max_height:
        max_height = new_message.height

    watcher.receive_consensus_message(new_message)  # here the watcher is, receiving all the messages

    if FREE_INSTANT_BROADCAST:
        for v in VALIDATOR_NAMES:
            validators[v].receive_consensus_message(new_message)
    else:
        # MAKE NEW MESSAGE VIEWABLE
        for v in VALIDATOR_NAMES:
            if v == next_proposer or v == 0:
                continue
            viewables[v][next_proposer].append(new_message)  # validators have the possibility of later viewing this message

        # RECEIVE CONSENSUS MESSAGES WITHIN SHARD
        for j in range(NUM_WITHIN_SHARD_RECEIPTS_PER_ROUND):

            next_receiver = random.choice(SHARD_VALIDATOR_ASSIGNMENT[rand_ID])

            pool = copy.copy(SHARD_VALIDATOR_ASSIGNMENT[rand_ID])
            pool.remove(next_receiver)

            new_received = False
            while(not new_received and len(pool) > 0):

                receiving_from = random.choice(pool)
                pool.remove(receiving_from)

                if len(viewables[next_receiver][receiving_from]) > 0:  # if they have any viewables at all
                    received_message = viewables[next_receiver][receiving_from][0]
                    try:
                        validators[next_receiver].receive_consensus_message(received_message)
                        viewables[next_receiver][receiving_from].remove(received_message)
                        new_received = True
                    except UnresolvedDeps:
                        pass

        # RECEIVE CONSENSUS MESSAGES BETWEEN SHARDS
        for j in range(NUM_BETWEEN_SHARD_RECEIPTS_PER_ROUND):

            pool = copy.copy(VALIDATOR_NAMES)
            pool.remove(0)

            next_receiver = random.choice(pool)
            pool.remove(next_receiver)

            new_received = False
            while(not new_received and len(pool) > 0):

                receiving_from = random.choice(pool)
                pool.remove(receiving_from)

                if len(viewables[next_receiver][receiving_from]) > 0:  # if they have any viewables at all
                    received_message = viewables[next_receiver][receiving_from][0]  # receive the next one in the list
                    try:
                        validators[next_receiver].receive_consensus_message(received_message)
                        viewables[next_receiver][receiving_from].remove(received_message)
                        new_received = True
                    except UnresolvedDeps:
                        pass

    # REPORTING:
    print("Step: ", i)
    if not REPORTING:
        continue
    if (i + 1) % REPORT_INTERVAL == 0:

        # VISUALIZATION
        plt.clf()
        fork_choice = watcher.fork_choice()
        SHARD_SPACING_CONSTANT = 3

        ValidatorDashes = nx.Graph();
        EndpointsPos = {}
        for v in VALIDATOR_NAMES:
            if v == 0:
                continue
            ValidatorDashes.add_node((v, 1))
            ValidatorDashes.add_node((v, 2))
            ValidatorDashes.add_edge((v, 1), (v, 2))
            EndpointsPos[(v, 1)] = (0,          SHARD_SPACING_CONSTANT*(1 - VALIDATOR_SHARD_ASSIGNMENT[v]) + NUM_VALIDATORS - v)
            EndpointsPos[(v, 2)] = (max_height, SHARD_SPACING_CONSTANT*(1 - VALIDATOR_SHARD_ASSIGNMENT[v]) + NUM_VALIDATORS - v)
        nx.draw_networkx_nodes(ValidatorDashes, EndpointsPos, node_size=0)
        nx.draw_networkx_edges(ValidatorDashes, EndpointsPos, style='dashed', width=0.5)

        PrevblockGraph = nx.DiGraph();
        ForkChoiceGraph = nx.DiGraph();
        SourcesGraph = nx.DiGraph();

        messagesPos = {}
        senders = {}
        block_to_message = {}

        messages = watcher.consensus_messages
        for m in messages:

            PrevblockGraph.add_node(m)
            ForkChoiceGraph.add_node(m)
            SourcesGraph.add_node(m)

            # get positions:
            if m.sender != 0:               
                messagesPos[m] = (m.height, SHARD_SPACING_CONSTANT*(1 - m.estimate.shard_ID) + NUM_VALIDATORS - m.sender)
            else:  # genesis blocks            
                messagesPos[m] = (m.height - 1, SHARD_SPACING_CONSTANT*(1 - m.estimate.shard_ID) + NUM_VALIDATORS/2 - m.estimate.shard_ID)

            # this map will help us draw nodes from prevblocks, sources, etc
            block_to_message[m.estimate] = m

            # define edges for prevblock graph
            if m.estimate.prevblock is not None:
                PrevblockGraph.add_edge(m, block_to_message[m.estimate.prevblock])

            for ID in SHARD_IDS:
               # SourcesGraph define edges
                if m.estimate.received_log.sources[ID] is not None:
                    SourcesGraph.add_edge(m, block_to_message[m.estimate.received_log.sources[ID]])

        # ForkChoiceGraph define edges
        for ID in SHARD_IDS:
            this_block = fork_choice[ID]
            while(this_block.prevblock is not None):
                ForkChoiceGraph.add_edge(block_to_message[this_block], block_to_message[this_block.prevblock])
                this_block = this_block.prevblock

        # Draw edges
        nx.draw_networkx_edges(SourcesGraph, messagesPos, style='dashdot', edge_color='y', arrowsize=10, width=1)
        nx.draw_networkx_edges(ForkChoiceGraph, messagesPos, edge_color='#66b266', arrowsize=25, width=15)
        nx.draw_networkx_edges(PrevblockGraph, messagesPos, width=3)

        nx.draw_networkx_nodes(PrevblockGraph, messagesPos, node_shape='s', node_color='#0066cc', node_size=300)

        ShardMessagesGraph = nx.Graph();
        ShardMessagesOriginGraph = nx.Graph();
        shard_messagesPos = {}

        message_sender_map = {}
        for m in messages:
            ShardMessagesOriginGraph.add_node(m)

            shard_messagesPos[m] = (m.height, SHARD_SPACING_CONSTANT*(1 - m.estimate.shard_ID) + NUM_VALIDATORS - m.sender)

            for ID in SHARD_IDS:
                for m2 in m.estimate.newly_sent()[ID]:
                    message_sender_map[m2] = m
                    ShardMessagesGraph.add_node(m2)
                    ShardMessagesOriginGraph.add_node(m2)
                    xoffset = rand.choice([rand.uniform(-0.5, -0.4), rand.uniform(0.4, 0.5)])
                    yoffset = rand.choice([rand.uniform(-0.5, -0.4), rand.uniform(0.4, 0.5)])
                    xoffset = 0
                    yoffset = -0.33 + 0.66*m.estimate.shard_ID
                    shard_messagesPos[m2] = (m.height + xoffset, SHARD_SPACING_CONSTANT*(1 - m.estimate.shard_ID) + NUM_VALIDATORS - m.sender + yoffset)
                    ShardMessagesOriginGraph.add_edge(m, m2)

        nx.draw_networkx_nodes(ShardMessagesOriginGraph, shard_messagesPos, node_size=0)
        nx.draw_networkx_nodes(ShardMessagesGraph, shard_messagesPos, node_shape='o', node_color='#f6546a', node_size=250)
        nx.draw_networkx_edges(ShardMessagesOriginGraph, shard_messagesPos, width=6, style='dotted')

        Orphaned_ShardMessagesDestinationGraph = nx.DiGraph();
        Agreeing_ShardMessagesDestinationGraph = nx.DiGraph();
        for m in messages:
            for ID in SHARD_IDS:
                for m2 in m.estimate.newly_received()[ID]:
                    if m2 in message_sender_map.keys():
                        A = fork_choice[message_sender_map[m2].estimate.shard_ID].is_in_chain(message_sender_map[m2].estimate)
                    else:
                        A = True
                    if fork_choice[m.estimate.shard_ID].is_in_chain(m.estimate) and A:
                        Agreeing_ShardMessagesDestinationGraph.add_edge(m2, m)
                    else:
                        Orphaned_ShardMessagesDestinationGraph.add_edge(m2, m)

        nx.draw_networkx_edges(Agreeing_ShardMessagesDestinationGraph, shard_messagesPos, edge_color='#600787', arrowsize=50, arrowstyle='->', width=6)
        nx.draw_networkx_edges(Orphaned_ShardMessagesDestinationGraph, shard_messagesPos, edge_color='#600787', arrowsize=20, arrowstyle='->', width=0.75)

        ax = plt.axes()

        # FLOATING TEXT
        ax.text(0, 0.2, 'child shard',
        horizontalalignment='right',
        verticalalignment='center',
        rotation='vertical',
        transform=ax.transAxes,
        size=25)

        ax.text(0, 0.75, 'parent shard',
        horizontalalignment='right',
        verticalalignment='center',
        rotation='vertical',
        transform=ax.transAxes,
        size=25)

        ax.text(0.1, 0, 'messages received by \n the child fork choice:',
        horizontalalignment='center',
        verticalalignment='bottom',
        transform=ax.transAxes,
        size=20)

        ax.text(0.1, -0.05, len(fork_choice[1].received_log.log[0]),
        horizontalalignment='center',
        verticalalignment='bottom',
        transform=ax.transAxes,
        size=30)

        ax.text(0.25, 0, 'messages sent by \n the child fork choice:',
        horizontalalignment='center',
        verticalalignment='bottom',
        transform=ax.transAxes,
        size=20)

        ax.text(0.25, -0.05, len(fork_choice[1].sent_log.log[0]),
        horizontalalignment='center',
        verticalalignment='bottom',
        transform=ax.transAxes,
        size=30)

        ax.text(0.1, 1, 'messages sent by \n the parent fork choice:',
        horizontalalignment='center',
        verticalalignment='bottom',
        transform=ax.transAxes,
        size=20)

        ax.text(0.1, 0.95, len(fork_choice[0].sent_log.log[1]),
        horizontalalignment='center',
        verticalalignment='bottom',
        transform=ax.transAxes,
        size=30)

        ax.text(0.25, 1, 'messages received by \n the parent fork choice:',
        horizontalalignment='center',
        verticalalignment='bottom',
        transform=ax.transAxes,
        size=20)

        ax.text(0.25, 0.95, len(fork_choice[0].received_log.log[1]),
        horizontalalignment='center',
        verticalalignment='bottom',
        transform=ax.transAxes,
        size=30)


        ax.text(0.4, 0, 'deadbeef balance on \n the child fork choice:',
        horizontalalignment='center',
        verticalalignment='bottom',
        transform=ax.transAxes,
        size=20)

        ax.text(0.4, -0.05, fork_choice[1].vm_state["pre"][DEADBEEF[2:].lower()]["balance"],
        horizontalalignment='center',
        verticalalignment='bottom',
        transform=ax.transAxes,
        size=30)

        ax.text(0.4, 1, 'deadbeef balance on \n the parent fork choice:',
        horizontalalignment='center',
        verticalalignment='bottom',
        transform=ax.transAxes,
        size=20)

        ax.text(0.4, 0.95, fork_choice[0].vm_state["pre"][DEADBEEF[2:].lower()]["balance"],
        horizontalalignment='center',
        verticalalignment='bottom',
        transform=ax.transAxes,
        size=30)



        plt.axis('off')
        plt.draw()
        plt.pause(PAUSE_LENGTH)

# Leave plot open after going over all proposals
mng = plt.get_current_fig_manager()
mng.window.showMaximized()
plt.show()
