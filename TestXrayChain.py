"""
Run unit tests against the Xray chain code without submitting to AwS.
"""

import unittest
import XrayChain


class XrayChainTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
