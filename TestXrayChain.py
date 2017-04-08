"""
Run unit tests against the Xray chain code without submitting to AwS.
"""

import unittest
import XrayChain


class XrayChainTests(unittest.TestCase):
    """
    Test the XrayChain class.
    """

    def test_fork1(self):
        """
        Ensure that you can't fork() from a chain with no messages.
        """
        chain = XrayChain.Chain(mock=True)
        exc = None
        try:
            chain.fork_subsegment()
        except RuntimeError as exc:
            pass
        assert exc is not None

    def test_fork2(self):
        """
        Ensure that a fork has the right parent.
        """
        chain = XrayChain.Chain(mock=True)
        segment_id = chain.log(0, 1, "RootEvent")
        child = chain.fork_subsegment()
        assert child.parent_id == segment_id
        child = chain.fork_root()
        assert child.parent_id == segment_id

    def test_fork3(self):
        """
        Ensure that child chains still can't be forked having never emitted a
        message
        """
        chain = XrayChain.Chain(mock=True)
        segment_id = chain.log(0, 1, "RootEvent")
        child = chain.fork_subsegment()
        assert child.parent_id == segment_id
        child = chain.fork_root()
        assert child.parent_id == segment_id
        try:
            child.fork_subsegment()
        except RuntimeError as exc:
            pass
        assert exc is not None

    def test_fork4(self):
        """
        Ensure that grandchild forks have the right parent_id
        """
        chain = XrayChain.Chain(mock=True)
        chain.log(0, 1, "RootEvent")
        child = chain.fork_subsegment()
        segment_id2 = child.log(1, 2, "ChildEvent")
        gchild = child.fork_subsegment()
        assert gchild.parent_id == segment_id2

    def test_fork5(self):
        """
        Ensure that setting the parent_id properly propagates to the fork.
        """
        chain = XrayChain.Chain(mock=True)
        segment_id = chain.log(0, 1, "RootEvent")
        child = chain.fork_subsegment()
        child.log(1, 2, "ChildEvent")
        gchild = child.fork_subsegment(parent_id=segment_id)
        assert gchild.parent_id == segment_id


if __name__ == "__main__":
    unittest.main()
