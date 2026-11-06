10 rem *** guess the number ***
20 print "{clear}{white}guess the number"
30 x=rnd(-ti):n=int(rnd(1)*100)+1:t=0
40 print "i'm thinking of a number from 1 to 100."
50 input "your guess";g
60 t=t+1
70 if g<n then print "higher!":goto 50
80 if g>n then print "lower!":goto 50
90 print "yes! it was";n;"- you took";t;"goes."
100 end
