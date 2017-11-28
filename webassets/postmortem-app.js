var myApp = angular.module('postmortemApp', ['ngResource']);

myApp.controller('postmortemController', ['$scope', '$rootScope', '$resource', '$timeout', function ($scope, $rootScope, $resource, $timeout) {
    
    $scope.snapNum = 1;
    $scope.numSnapshots = 1;
    $scope.loadingStart = new Date();
    $scope.loading = true;
    $scope.flagNames = [];

    fetch("score_snapshots.json")
        .then(response => response.json())
        .then(function(rjson) {
            $scope.snapshots = rjson;
            $scope.numSnapshots = $scope.snapshots.length;
            $scope.loadTime = (new Date()) - $scope.loadingStart;
            $scope.loading = false;
            $scope.sliderChange();
            $scope.$apply();
            console.log("Load complete");
        });

    $scope.sliderChange = function() {
        // Basic structure expected:
        // - timestamp: time in seconds from unix epoch
        // - score_snapshots: mapping from team ID to a dict from flag name to boolean
        //
        // Process: 

        var snap = $scope.snapshots[$scope.snapNum - 1];
        $scope.curSnapTimestamp = (new Date(snap.timestamp * 1000)).toString();
        var flagNamesUnsorted = Object.keys(snap.score_snapshots[Object.keys(snap.score_snapshots)[0]].bitmask);
        flagNamesUnsorted.sort();
        $scope.flagNames = flagNamesUnsorted;
        teamFlags = {};
        teamScores = {};
        teamNames = {}
        teamIds = Object.keys(snap.score_snapshots).map(function(v) {
            if (parseInt(v) < 10) {
                return "0" + v;
            } else {
                return v;
            }
        });
        teamIds.sort();
        $scope.teamIds = teamIds.map(function(teamId) {
            for (namePair in TEAMS) {
                if (parseInt(TEAMS[namePair].team_id) == parseInt(teamId)) {
                    teamNames[parseInt(teamId)] = TEAMS[namePair].team_name
                    return TEAMS[namePair].team_name;
                }
            }
        });
        for (var i = 0 ; i < teamIds.length; i++) {
            var teamId = parseInt(teamIds[i]);
            teamScores[teamId] = snap.score_snapshots[teamId].score;
            teamFlags[teamId] = $scope.flagNames.map(fn => snap.score_snapshots[teamId].bitmask[fn]);
        }

        $scope.teamNames = teamNames;
        $scope.teamScores = teamScores;
        $scope.teamFlags = teamFlags;
    };
}]);
